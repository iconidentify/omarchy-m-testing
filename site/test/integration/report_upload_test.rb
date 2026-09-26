require "test_helper"

# Seam B: post reports to the upload API, then assert on the API responses,
# what is stored and the pages.
class ReportUploadTest < ActionDispatch::IntegrationTest
  test "posting the golden report stores it and returns report and deletion links" do
    upload_report golden("m2-max-image2")

    assert_response :created
    links = response.parsed_body
    report = Report.sole
    assert_equal GoldenReports.json("m2-max-image2"), report.body
    assert_equal 1, report.schema_version
    assert_equal "http://www.example.com/reports/#{report.public_id}", links["report_url"]
    assert_match %r{\Ahttp://www.example.com/reports/#{report.public_id}/deletion\?token=[\w-]{40,}\z}, links["deletion_url"]
    assert_equal report.public_id, links["id"]
  end

  test "the report page shows the machine and each check" do
    upload_report golden("m2-max-image2")
    get path_of(response.parsed_body["report_url"])

    assert_response :success
    assert_select "h1", "Apple MacBook Pro (16-inch, M2 Max, 2023)"
    assert_select "dd", /M2 Max \(t6021, board j416c\)/
    assert_select "dd", "7.1.12-2-2-ARCH"
    assert_select "li#check-system\\.identity .status", "PASS"
    assert_select "li#check-system\\.identity .evidence", /kernel: 7\.1\.12-2-2-ARCH/
  end

  test "every golden report is accepted" do
    assert GoldenReports.paths.any?
    GoldenReports.paths.each do |path|
      upload_report JSON.parse(File.read(path))
      assert_response :created, "#{File.basename(path)}: #{response.body}"
    end
  end

  test "reports that don't match the schema are rejected and not stored" do
    with_serial = GoldenReports.json("m2-max-image2").tap { |r| r["machine"]["serial_number"] = "C02XXXXXXXXX" }
    bad_check_id = GoldenReports.json("m2-max-image2").tap { |r| r["checks"][0]["id"] = "Not An Id" }
    unclassified = GoldenReports.json("m2-max-image2").tap { |r| r["checks"][0].delete("classification") }
    no_catalogue_version = GoldenReports.json("m2-max-image2").tap { |r| r.delete("catalogue_version") }
    newer = GoldenReports.json("m2-max-image2").tap { |r| r["schema_version"] = 2 }
    not_an_object = []

    [ with_serial, bad_check_id, unclassified, no_catalogue_version, newer, not_an_object ].each do |report|
      upload_report report
      assert_response :unprocessable_content
      assert_match "does not match report schema v1", response.parsed_body["error"]
      assert response.parsed_body["details"].any?
    end
    assert_equal 0, Report.count
  end

  test "check ids the feature catalogue doesn't know are rejected with an upgrade message" do
    report = GoldenReports.json("m2-max-image2").tap { |r| r["checks"][0]["id"] = "made.up" }

    upload_report report

    assert_response :unprocessable_content
    assert_match "Update omarchy-m-test", response.parsed_body["error"]
    assert_equal [ "unknown check id made.up" ], response.parsed_body["details"]
    assert_equal 0, Report.count
  end

  test "every check id in the golden reports is in the feature catalogue" do
    GoldenReports.paths.each do |path|
      assert_empty Catalogue.unknown_check_ids(JSON.parse(File.read(path))), File.basename(path)
    end
  end

  test "the report page explains each result in plain words, with its layer and catalogue version" do
    upload_report golden("m2-max-image2")
    get path_of(response.parsed_body["report_url"])

    assert_select "li#check-system\\.identity .outcome.outcome-works", "works"
    assert_select "li#check-system\\.identity .feature", "Device tree, asahi layer"
    assert_select "dd", "feature catalogue v#{GoldenReports.json("m2-max-image2").fetch("catalogue_version")}"
    assert_select ".credit", /CC BY 3\.0/
  end

  test "a failed result shows the catalogue's words for its outcome" do
    report = GoldenReports.json("m2-max-image2")
    report["checks"][0].merge!("status" => "fail", "classification" => report["checks"][0]["classification"].merge("outcome" => "not-in-aurora"))

    upload_report report
    get path_of(response.parsed_body["report_url"])

    assert_select "li#check-system\\.identity .outcome.outcome-not-in-aurora", "not yet supported by Aurora"
  end

  test "a body that isn't JSON is a bad request" do
    upload_report "not json"

    assert_response :bad_request
    assert_equal 0, Report.count
  end

  test "oversized reports are refused before parsing" do
    upload_report TestMachines.sign(GoldenReports.json("m2-max-image2")).merge("padding" => "x" * 300.kilobytes).to_json

    assert_response :content_too_large
    assert_equal 0, Report.count
  end

  test "the deletion link deletes the report" do
    upload_report golden("m2-max-image2")
    links = response.parsed_body

    get path_of(links["deletion_url"])
    assert_response :success
    assert_select "button", "Delete report"

    token = Rack::Utils.parse_query(URI(links["deletion_url"]).query)["token"]
    delete path_of(links["report_url"]), params: { token: token }
    assert_response :success
    assert_equal 0, Report.count

    get path_of(links["report_url"])
    assert_response :not_found
  end

  test "deleting removes the report and its evidence completely, hidden or not" do
    links = upload_report(golden("m2-max-image2"))
    Report.sole.update!(hidden_at: Time.current)
    evidence = GoldenReports.json("m2-max-image2")["checks"].find { |check| check["id"] == "setup.first-boot-hardware" }["evidence"].first

    token = Rack::Utils.parse_query(URI(links["deletion_url"]).query)["token"]
    get path_of(links["deletion_url"])
    assert_response :success
    delete path_of(links["report_url"]), params: { token: token }

    assert_response :success
    assert_select "p", /its evidence have been removed/
    assert_equal 0, Report.count
    assert_equal 0, ActiveRecord::Base.connection.select_value("SELECT count(*) FROM reports WHERE body::text LIKE #{ActiveRecord::Base.connection.quote("%#{evidence}%")}")
    get "/api/v1/checks.csv"
    assert_not_includes response.body, links["id"]
  end

  test "a wrong deletion token deletes nothing" do
    upload_report golden("m2-max-image2")
    report_path = path_of(response.parsed_body["report_url"])

    get "#{report_path}/deletion", params: { token: "wrong" }
    assert_response :not_found
    delete report_path, params: { token: "wrong" }
    assert_response :not_found
    delete report_path
    assert_response :not_found
    assert_equal 1, Report.count
  end
end
