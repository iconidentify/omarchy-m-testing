require "test_helper"

# Seam B: what the upload API refuses beyond the schema: outdated clients and
# too many uploads from one network or one machine.
class UploadRulesTest < ActionDispatch::IntegrationTest
  test "a report in an outdated schema is refused with an upgrade message" do
    [ 0, -1 ].each do |version|
      body = upload_report golden("m2-max-image2").merge("schema_version" => version)

      assert_response :unprocessable_content
      assert_equal "This report uses report schema v#{version}, which is outdated: the site accepts v1. " \
                   "Update omarchy-m-test (curl -fsSL http://www.example.com/install | bash) and run it again.", body["error"]
      assert_equal [ "schema_version #{version} is older than 1" ], body["details"]
    end
    assert_equal 0, Report.count
  end

  test "unknown check ids get the same upgrade instructions" do
    body = upload_report golden("m2-max-image2").tap { |r| r["checks"][0]["id"] = "made.up" }

    assert_response :unprocessable_content
    assert_match "(curl -fsSL http://www.example.com/install | bash)", body["error"]
  end

  test "uploads are rate-limited per IP address, whichever machines they come from" do
    limit = Api::V1::ReportsController::UPLOADS_PER_HOUR
    limit.times { |n| upload_report golden("m2-max-image2"), machine: "m#{n}", ip: "10.0.0.1" }
    assert_response :created

    body = upload_report golden("m2-max-image2"), machine: "another", ip: "10.0.0.1"
    assert_response :too_many_requests
    assert_match "Too many uploads from your network: at most #{limit} an hour", body["error"]
    # refused uploads count too, so a flood of junk is limited as well
    upload_report "not json", ip: "10.0.0.1"
    assert_response :too_many_requests

    upload_report golden("m2-max-image2"), machine: "another", ip: "10.0.0.2"
    assert_response :created
    assert_equal limit + 1, Report.count
  end

  test "uploads are rate-limited per machine key, from any network" do
    limit = Api::V1::ReportsController::UPLOADS_PER_HOUR_PER_MACHINE
    limit.times { |n| upload_report golden("m2-max-image2"), machine: "a", ip: "10.0.1.#{n}" }
    assert_response :created

    body = upload_report golden("m2-max-image2"), machine: "a", ip: "10.0.2.1"
    assert_response :too_many_requests
    assert_equal "Too many uploads from this Mac: at most #{limit} an hour. Try again later; the report is saved on your Mac.", body["error"]

    upload_report golden("m2-max-image2"), machine: "b", ip: "10.0.2.1"
    assert_response :created
    assert_equal limit + 1, Report.count
  end

  test "reports with a forged signature don't use up the real machine's uploads" do
    limit = Api::V1::ReportsController::UPLOADS_PER_HOUR_PER_MACHINE
    forged = TestMachines.sign(golden("m2-max-image2"), "mallory")
    forged["signature"]["public_key"] = TestMachines.public_key("a")
    (limit + 1).times { |n| upload_report forged.to_json, ip: "10.0.1.#{n}" }
    assert_response :unprocessable_content

    upload_report golden("m2-max-image2"), machine: "a", ip: "10.0.2.1"
    assert_response :created
  end

  test "behind a proxy the client address comes from the configured header, never from X-Forwarded-For" do
    ENV["CLIENT_IP_HEADER"] = "X-Real-IP"
    limit = Api::V1::ReportsController::UPLOADS_PER_HOUR
    upload = lambda do |real_ip, n|
      post "/api/v1/reports", params: TestMachines.sign(golden("m2-max-image2"), "m#{n}").to_json,
                              headers: { "Content-Type" => "application/json", "X-Real-IP" => real_ip, "X-Forwarded-For" => "198.51.100.#{n}" }
    end

    limit.times { |n| upload.call("203.0.113.9", n) }
    upload.call("203.0.113.9", limit)
    assert_response :too_many_requests
    upload.call("203.0.113.10", limit)
    assert_response :created
  end
end
