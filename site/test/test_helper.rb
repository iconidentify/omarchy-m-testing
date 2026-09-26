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

class ActionDispatch::IntegrationTest
  include Uploads

  setup do
    Api::V1::ReportsController::RATE_LIMITS.clear
    ENV.delete("ADMIN_TOKEN")
    ENV.delete("CLIENT_IP_HEADER")
  end
end
