require "test_helper"

# Seam B: the evidence rules (text only, at most 64 KiB per report) hold at
# upload too, for reports that pass the schema.
class ReportEvidenceTest < ActionDispatch::IntegrationTest
  def upload(report) = upload_report(report)

  def with_checks(*evidence)
    GoldenReports.json("m2-max-image2").tap do |report|
      report["checks"] = evidence.map { |lines| report["checks"][0].merge("evidence" => lines) }
    end
  end

  test "every golden report is within the evidence rules" do
    GoldenReports.paths.each do |path|
      assert_empty ReportEvidence.errors(JSON.parse(File.read(path))), File.basename(path)
    end
  end

  test "a report with more than 64 KiB of evidence is refused" do
    upload with_checks(*Array.new(3) { Array.new(50, "x" * 500) })

    assert_response :unprocessable_content
    assert_match "at most 64 KiB", response.parsed_body["error"]
    assert_match "a report carries at most 65536", response.parsed_body["details"].first
    assert_equal 0, Report.count
  end

  test "64 KiB of evidence is accepted" do
    upload with_checks(Array.new(50, "x" * 500), Array.new(50, "x" * 500), Array.new(31, "x" * 500) + [ "x" * 36 ])

    assert_response :created
  end

  test "evidence that isn't text is refused" do
    [ "PNG\u0000\u001a", "two\nlines", "caf\u{fffd}" ].each do |line|
      upload with_checks([ "ok", line ])

      assert_response :unprocessable_content
      assert_equal [ "evidence line 2 is not text" ], response.parsed_body["details"]
    end
    assert_equal 0, Report.count
  end
end
