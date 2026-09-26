require "test_helper"

# Seam B: benchmark scores upload with the report (the CLI's golden benchmark
# report, schema/golden/benchmarks/) and are compared per Mac model and
# Omarchy stack/version.
class BenchmarksTest < ActionDispatch::IntegrationTest
  M2 = "benchmarks/m2-max-converged"

  # The golden benchmark run with its scores scaled, optionally on another Mac (a corpus golden's machine and system).
  def run_with(factor, on: nil, suite: nil)
    golden(M2).tap do |report|
      if on
        other = golden(on)
        report["machine"] = other["machine"]
        report["system"] = other["system"]
      end
      report["checks"].each do |check|
        next unless check["score"]

        check["score"]["value"] = (check["score"]["value"] * factor).round
        check["score"]["suite"] = suite if suite
      end
    end
  end

  def opengl_rows = css_select("#benchmark-opengl-suite-1 tr.score-row")

  test "the golden benchmark report uploads with its scores" do
    body = upload_report golden(M2)

    assert_response :created
    stored = Report.find_by!(public_id: body["id"])
    assert_equal({ "value" => 2987, "unit" => "points", "tool" => "glmark2 2023.01", "suite" => 1 },
                 stored.checks.find { |check| check["id"] == "benchmark.opengl" }["score"])
  end

  test "each benchmark compares Macs, best first, each machine counted once with its latest score" do
    upload_report run_with(0.5), machine: "a"                        # an older run on the same M2: replaced by the next
    upload_report golden(M2), machine: "a"
    upload_report run_with(1.1), machine: "c"                        # a second M2 Max
    upload_report run_with(0.6, on: "m1-pro-converged"), machine: "b"

    get "/benchmarks"

    assert_response :success
    assert_select "#benchmark-opengl-suite-1 .card-title", "opengl · suite 1"
    assert_equal [ "j416c", "j314s" ], opengl_rows.map { |row| row["data-board"] }
    m2, m1 = opengl_rows
    # The M2's two machines: 2987 and 3286 (the median is between them); the older 1494 run doesn't count.
    assert_select m2, ".score-value", "3,136.5"
    assert_select m2, ".score-range", "2,987–3,286"
    assert_select m2, "td", /\A2 \(3 runs\)\z/
    assert_select m2, ".score-bar[style=?]", "--share: 100.0%"
    assert_select m1, ".score-value", "1,792"
    assert_select m1, ".score-bar[style=?]", "--share: 57.1%"
    assert_select m1, "td", "converged 4.0.0"
    assert_select "#benchmark-h264-decode-suite-1 tr.score-row .score-value", "691"
    assert_select "#benchmark-vulkan-suite-1 tr.score-row td.dim", "vkmark 2025.01"
    assert_select ".site-nav a.current", "Benchmarks"
  end

  test "scores from another suite are never compared with these" do
    upload_report golden(M2), machine: "a"
    upload_report run_with(2.0, suite: 2), machine: "b"

    get "/benchmarks"

    assert_equal 1, opengl_rows.size
    assert_select "#benchmark-opengl-suite-2 tr.score-row .score-value", "5,974"
    assert_select "#benchmark-opengl-suite-1 tr.score-row .score-value", "2,987"
  end

  test "runs without scores, and hidden reports, add nothing" do
    upload_report golden("m2-max-converged")                       # its benchmarks were skipped
    hidden = upload_report golden(M2), machine: "b"
    Report.find_by!(public_id: hidden["id"]).update!(hidden_at: Time.current)

    get "/benchmarks"

    assert_response :success
    assert_select ".score-row", 0
    assert_select ".card", /No report has a benchmark score yet/
  end

  test "a model page shows its scores against the best Mac, and the report shows each score" do
    upload_report golden(M2), machine: "a"
    m1 = upload_report run_with(0.6, on: "m1-pro-converged"), machine: "b"

    get "/models/j314s"
    assert_select "#benchmarks tr.score-row", 4
    assert_select %(#benchmarks tr.score-row[data-benchmark="opengl-suite-1"] .score-value), "1,792"
    assert_select %(#benchmarks tr.score-row[data-benchmark="opengl-suite-1"] .score-bar[style=?]), "--share: 60.0%"

    get path_of(m1["report_url"])
    assert_select "li#check-benchmark\\.opengl .score", /score 1,792 points \(glmark2 2023\.01, suite 1\)/
    assert_select "li#check-benchmark\\.hevc-decode .score a[href=?]", "/benchmarks#benchmark-hevc-decode-suite-1"
  end

  test "the comparison and every score download under CC0" do
    upload_report golden(M2), machine: "a"

    get "/api/v1/benchmarks.json"
    assert_response :success
    body = response.parsed_body
    assert_equal "CC0-1.0", body.dig("license", "id")
    opengl = body["benchmarks"].find { |benchmark| benchmark["check"] == "benchmark.opengl" }
    assert_equal({ "model" => "MacBook Pro (16-inch, M2 Max, 2023)", "board" => "j416c", "soc" => "t6021", "chip" => "M2 Max",
                   "stack" => "converged", "version" => "4.0.0", "score" => 2987, "low" => 2987, "high" => 2987, "machines" => 1,
                   "runs" => 1, "tools" => [ "glmark2 2023.01" ] }, opengl["rows"].sole)
    assert_not_includes response.body, Report.first.machine_id

    get "/api/v1/checks.csv"
    header, *rows = response.body.split("\r\n").map { |line| line.scan(/"((?:[^"]|"")*)"/).flatten }
    row = header.zip(rows.find { |r| r.include?("benchmark.vulkan") }).to_h
    assert_equal({ "score" => "6124", "score_unit" => "points", "score_tool" => "vkmark 2025.01", "score_suite" => "1" },
                 row.slice("score", "score_unit", "score_tool", "score_suite"))
  end

  test "a score outside the schema is refused" do
    [
      ->(score) { score["unit"] = "percent" },
      ->(score) { score["value"] = -1 },
      ->(score) { score["value"] = "2987" },
      ->(score) { score["tool"] = "glmark2 <script>" },
      ->(score) { score["serial"] = "C02XYZ" },
      ->(score) { score.delete("suite") }
    ].each do |change|
      report = golden(M2)
      change.call(report["checks"].first["score"])
      body = upload_report report

      assert_response :unprocessable_content
      assert_match "report schema v1", body["error"]
    end
    assert_equal 0, Report.count
  end
end
