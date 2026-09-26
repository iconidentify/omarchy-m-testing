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
end

# Uploads through the API, as the CLI does, from a given IP address: until
# reports carry machine keys, distinct addresses are distinct machines.
module Uploads
  def upload_report(report, ip: "10.0.0.1")
    text = report.is_a?(String) ? report : report.to_json
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
