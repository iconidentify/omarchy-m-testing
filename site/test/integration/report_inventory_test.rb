require "test_helper"

# Seam B: the hardware inventory of the golden reports on the report page.
class ReportInventoryTest < ActionDispatch::IntegrationTest
  def upload_and_show(name)
    upload_report golden(name)
    assert_response :created
    get URI(response.parsed_body["report_url"]).request_uri
    assert_response :success
  end

  # Hardware the catalogue doesn't know (none on the recorded Macs since DisplayPort audio is catalogued).
  UNKNOWN = { "compatible" => "apple,t6020-mystery", "count" => 1, "outcome" => "unknown-hardware" }.freeze

  test "the report page lists the hardware no driver claimed, unknown hardware first" do
    upload_report(golden("m2-max-image2").tap do |r|
      r["inventory"]["nodes"] << { "compatible" => UNKNOWN["compatible"], "status" => "okay", "driver" => "unbound", "count" => 1 }
      r["inventory"]["unclaimed"] << UNKNOWN.dup
    end)
    assert_response :created
    get URI(response.parsed_body["report_url"]).request_uri
    assert_response :success

    assert_select "#inventory h2.section-title", "hardware inventory"
    assert_select "#inventory .inventory-summary", /425 hardware nodes: 366 claimed by a driver, 27 with no device of their own, 5 bus or register containers with no driver of their own, 23 disabled, 4 unclaimed\./
    assert_select "#inventory ul.unknown-hardware li", 1
    assert_select "#inventory ul.unknown-hardware li", /apple,t6020-mystery \(1 node\): unknown hardware/
    assert_select "#inventory ul.unclaimed-hardware li", /apple,t6020-avd \(1 node\): doesn't work, but should on this Mac \(Video decoder, asahi layer\)/
    assert_select "#inventory ul.unclaimed-hardware li", /apple,t6020-dpaudio \(2 nodes\): not yet supported by Asahi \(DisplayPort audio, asahi layer\)/
  end

  test "the report page lists the kernel's build options that differ from Asahi's" do
    upload_and_show "m2-max-image2"

    assert_select "#inventory p", /22 options differ from Asahi's linux-asahi 7\.1\.13\.asahi3-2 \(asahi-alarm\/PKGBUILDs@d585b07\)/
    assert_select "#inventory table.kernel-config tbody tr", 22
    assert_select "#inventory table.kernel-config td code", "CONFIG_USB4"
  end

  test "the M1 has no unknown hardware: its DisplayPort audio isn't in Asahi yet" do
    upload_and_show "m1-pro-mx-mac"

    assert_select "#inventory ul.unknown-hardware", 0
    assert_select "#inventory p.dim", /None: every node on this Mac is either claimed by a driver or known to the feature catalogue/
    assert_select "#inventory ul.unclaimed-hardware li", /apple,t6000-dpaudio \(1 node\): not yet supported by Asahi \(DisplayPort audio, asahi layer\)/
  end

  test "a report without an inventory shows no hardware section" do
    report = GoldenReports.json("m2-max-image2").tap { |r| r.delete("inventory") }
    upload_report report
    assert_response :created
    get URI(response.parsed_body["report_url"]).request_uri

    assert_response :success
    assert_select "#inventory", 0
  end

  test "inventory fields outside the schema are rejected" do
    with_path = GoldenReports.json("m2-max-image2").tap { |r| r["inventory"]["nodes"][0]["path"] = "/soc/gpu@406400000" }
    with_value = GoldenReports.json("m2-max-image2").tap { |r| r["inventory"]["nodes"][0]["compatible"] = "serial-number = C02XXXXXXXXX" }

    [ with_path, with_value ].each do |report|
      upload_report report
      assert_response :unprocessable_content
      assert_match "does not match report schema", response.parsed_body["error"]
    end
    assert_equal 0, Report.count
  end
end
