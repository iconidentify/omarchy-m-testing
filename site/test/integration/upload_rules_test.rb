require "test_helper"

# Seam B: what the upload API refuses beyond the schema: outdated clients and
# too many uploads from one address.
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

  test "uploads are rate-limited per IP address" do
    limit = Api::V1::ReportsController::UPLOADS_PER_HOUR
    limit.times { upload_report golden("m2-max-image2"), ip: "10.0.0.1" }
    assert_response :created

    body = upload_report golden("m2-max-image2"), ip: "10.0.0.1"
    assert_response :too_many_requests
    assert_match "Too many uploads from your network: at most #{limit} an hour", body["error"]
    # refused uploads count too, so a flood of junk is limited as well
    upload_report "not json", ip: "10.0.0.1"
    assert_response :too_many_requests

    upload_report golden("m2-max-image2"), ip: "10.0.0.2"
    assert_response :created
    assert_equal limit + 1, Report.count
  end

  test "behind a proxy the client address comes from the configured header" do
    ENV["CLIENT_IP_HEADER"] = "X-Real-IP"
    limit = Api::V1::ReportsController::UPLOADS_PER_HOUR
    upload = ->(real_ip) { post "/api/v1/reports", params: GoldenReports.text("m2-max-image2"), headers: { "Content-Type" => "application/json", "X-Real-IP" => real_ip } }

    limit.times { upload.call("203.0.113.9") }
    upload.call("203.0.113.9")
    assert_response :too_many_requests
    upload.call("203.0.113.10")
    assert_response :created
    assert_equal [ 1, limit ], Report.group(:machine_id).count.values.sort
  end

  test "the machine id is a keyed digest, never the address itself" do
    upload_report golden("m2-max-image2"), ip: "10.0.0.7"

    machine_id = Report.sole.machine_id
    assert_match(/\Aip:\h{20}\z/, machine_id)
    assert_not_includes machine_id, "10.0.0.7"
    assert_not_equal machine_id, Report.machine_id_for_ip("10.0.0.8")
  end
end
