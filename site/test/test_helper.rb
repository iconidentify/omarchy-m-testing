ENV["RAILS_ENV"] ||= "test"
require_relative "../config/environment"
require "rails/test_help"

module ActiveSupport
  class TestCase
    parallelize(workers: :number_of_processors)
  end
end

# The golden reports shared with the CLI's Seam A tests (schema/golden/).
module GoldenReports
  def self.paths = Dir[ReportSchema.dir.join("golden", "*.json")].sort
  def self.text(name) = ReportSchema.dir.join("golden", "#{name}.json").read
  def self.json(name) = JSON.parse(text(name))

  # The same reports as the CLI signs them with its fixture key (cli/tests/fixtures/).
  def self.signed_paths = Dir[ReportSchema.dir.join("golden", "signed", "*.json")].sort
end

# Test machines: an ed25519 key per name, made from the name so every run
# signs the same way, signing reports as the CLI does (ssh-keygen -Y sign).
module TestMachines
  def self.key(name) = OpenSSL::PKey.new_raw_private_key("ED25519", OpenSSL::Digest::SHA256.digest("test machine #{name}"))

  def self.key_blob(name)
    MachineSignature::SshReader.pack(MachineSignature::KEY_TYPE) + MachineSignature::SshReader.pack(key(name).raw_public_key)
  end

  def self.public_key(name) = "#{MachineSignature::KEY_TYPE} #{Base64.strict_encode64(key_blob(name))}"
  def self.machine_id(name) = MachineSignature.machine_id_for(key_blob(name))

  # The report with the signature `name`'s key makes over it (any old one replaced).
  def self.sign(report, name = "a")
    report = report.except("signature")
    pack = MachineSignature::SshReader.method(:pack)
    namespace, hash = MachineSignature::NAMESPACE, "sha512"
    signed = "SSHSIG" + [ namespace, "", hash, OpenSSL::Digest::SHA512.digest(MachineSignature.canonical(report)) ].map(&pack).join
    raw = key(name).sign(nil, signed)
    blob = "SSHSIG" + [ 1 ].pack("N") + [ key_blob(name), namespace, "", hash, pack.call(MachineSignature::KEY_TYPE) + pack.call(raw) ].map(&pack).join
    armored = "-----BEGIN SSH SIGNATURE-----\n#{Base64.strict_encode64(blob).scan(/.{1,70}/).join("\n")}\n-----END SSH SIGNATURE-----"
    report.merge("signature" => { "public_key" => public_key(name), "signature" => armored })
  end
end

# Uploads through the API, as the CLI does: signed by a test machine's key
# (machine:), from an IP address (ip:). A String is posted as it is.
module Uploads
  def upload_report(report, machine: "a", ip: "10.0.0.1")
    text = report.is_a?(Hash) ? TestMachines.sign(report, machine).to_json : report.is_a?(String) ? report : report.to_json
    post "/api/v1/reports", params: text, headers: { "Content-Type" => "application/json", "Accept" => "application/json" },
                            env: { "REMOTE_ADDR" => ip }
    response.parsed_body
  end

  def golden(name) = GoldenReports.json(name)

  # The golden report with some checks' status and outcome changed: { "display.backlight" => "fails" }.
  def golden_with(name, outcomes)
    golden(name).tap do |report|
      report["checks"].each do |check|
        outcome = outcomes[check["id"]] or next
        check["status"] = { "works" => "pass", "not-tested" => "skip" }.fetch(outcome, "fail")
        check["classification"]["outcome"] = outcome
      end
    end
  end

  def path_of(url) = URI(url).request_uri
end

# GitHub, as the site sees it (Github::HttpClient's interface): tokens this
# OAuth app issued, other apps' tokens, and web-flow codes.
class FakeGithub
  attr_reader :app_tokens, :other_tokens, :codes, :revoked, :exchanges

  def initialize
    @app_tokens = {}
    @other_tokens = {}
    @codes = {}
    @revoked = []
    @exchanges = []
  end

  # A token this app issued to `login`.
  def issue(token, login, id: login.sum)
    app_tokens[token] = Github::Identity.new(login:, id:)
    token
  end

  def exchange_code(code:, redirect_uri:)
    exchanges << redirect_uri
    codes.delete(code) or raise Github::Error, "The code passed is incorrect or expired."
  end

  def user(token) = app_tokens[token] || other_tokens[token] || raise(Github::Error, "GitHub answered HTTP 401")
  def app_token_user(token) = app_tokens[token] || raise(Github::Error, "GitHub answered HTTP 404")
  def revoke(token) = revoked << token
end

# The golden tester sign-in the CLI sends (schema/golden/sign-in/), signed by
# the CLI's fixture key, the same key as the signed golden reports.
module GoldenSignIn
  TOKEN = "gho_goldenTesterToken0123456789"

  def self.text = ReportSchema.dir.join("golden", "sign-in", "tester-sign-in.json").read
  def self.json = JSON.parse(text)
end

module TesterSignIns
  def github = Github.client

  def configure_github(admins: "maralcbr")
    ENV["GITHUB_CLIENT_ID"] = "Ov23test"
    ENV["GITHUB_CLIENT_SECRET"] = "test-secret"
    ENV["ADMIN_GITHUB_LOGINS"] = admins
  end

  def sign_in_tester(body = GoldenSignIn.text, ip: "10.0.0.1")
    body = body.to_json unless body.is_a?(String)
    post "/api/v1/tester_bindings", params: body, headers: { "Content-Type" => "application/json", "Accept" => "application/json" },
                                     env: { "REMOTE_ADDR" => ip }
    response.parsed_body
  end

  # A test machine (TestMachines) bound to `login`, as a sign-in on it would.
  def bind_machine(name, login) = TesterBinding.bind!(machine_id: TestMachines.machine_id(name), identity: Github::Identity.new(login:, id: login.sum))

  # Signs in to /admin through the (fake) GitHub web flow as `login`.
  def sign_in_admin_with_github(login = "maralcbr")
    post "/admin/session"
    state = Rack::Utils.parse_query(URI(response.location).query).fetch("state")
    github.codes["code-#{login}"] = github.issue("token-#{login}", login)
    get "/auth/github/callback", params: { code: "code-#{login}", state: }
  end
end

class ActionDispatch::IntegrationTest
  include Uploads
  include TesterSignIns

  setup do
    Api::V1::ReportsController::RATE_LIMITS.clear
    %w[ADMIN_TOKEN CLIENT_IP_HEADER GITHUB_CLIENT_ID GITHUB_CLIENT_SECRET ADMIN_GITHUB_LOGINS].each { |name| ENV.delete(name) }
    Github.client = FakeGithub.new
  end
end
