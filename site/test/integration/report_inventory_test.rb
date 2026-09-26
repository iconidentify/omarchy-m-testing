require "test_helper"

# Seam B: the hardware inventory of the golden reports on the report page.
class ReportInventoryTest < ActionDispatch::IntegrationTest
  def upload_and_show(name)
    post "/api/v1/reports", params: GoldenReports.text(name), headers: { "Content-Type" => "application/json", "Accept" => "application/json" }
    assert_response :created
    get URI(response.parsed_body["report_url"]).request_uri
    assert_response :success
  end

  test "the report page lists the hardware no driver claimed, unknown hardware first" do
    upload_and_show "m2-max-image2"

    assert_select "#inventory h2", "Hardware"
    assert_select "#inventory .inventory-summary", /424 hardware nodes: 366 claimed by a driver, 27 with no device of their own, 5 bus or register containers with no driver of their own, 23 disabled, 3 unclaimed\./
    assert_select "#inventory ul.unknown-hardware li", 1
    assert_select "#inventory ul.unknown-hardware li", /apple,t6020-dpaudio \(2 nodes\): unknown hardware/
    assert_select "#inventory ul.unclaimed-hardware li", /apple,t6020-avd \(1 node\): doesn't work, but should on this Mac \(Video decoder, asahi layer\)/
  end

  test "the report page lists the kernel's build options that differ from Asahi's" do
    upload_and_show "m2-max-image2"

    assert_select "#inventory p", /22 options differ from Asahi's linux-asahi 7\.1\.13\.asahi3-2 \(asahi-alarm\/PKGBUILDs@d585b07\)/
    assert_select "#inventory table.kernel-config tbody tr", 22
    assert_select "#inventory table.kernel-config td code", "CONFIG_USB4"
  end

  test "the M1's unknown hardware" do
    upload_and_show "m1-pro-mx-mac"

    assert_select "#inventory ul.unknown-hardware li", /apple,t6000-dpaudio \(1 node\): unknown hardware/
    assert_select "#inventory ul.unclaimed-hardware", 0
  end

  test "a report without an inventory shows no hardware section" do
    report = GoldenReports.json("m2-max-image2").tap { |r| r.delete("inventory") }
    post "/api/v1/reports", params: report.to_json, headers: { "Content-Type" => "application/json", "Accept" => "application/json" }
    assert_response :created
    get URI(response.parsed_body["report_url"]).request_uri

    assert_response :success
    assert_select "#inventory", 0
  end

  test "inventory fields outside the schema are rejected" do
    with_path = GoldenReports.json("m2-max-image2").tap { |r| r["inventory"]["nodes"][0]["path"] = "/soc/gpu@406400000" }
    with_value = GoldenReports.json("m2-max-image2").tap { |r| r["inventory"]["nodes"][0]["compatible"] = "serial-number = C02XXXXXXXXX" }

    [ with_path, with_value ].each do |report|
      post "/api/v1/reports", params: report.to_json, headers: { "Content-Type" => "application/json", "Accept" => "application/json" }
      assert_response :unprocessable_content
    end
    assert_equal 0, Report.count
  end
end
