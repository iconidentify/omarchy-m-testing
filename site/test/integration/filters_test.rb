require "test_helper"

# Seam B: the filter bar on the matrix and the reports list (ReportFilter).
# Every filter is a query parameter, so a filtered view is a link that works
# without JavaScript; filters combine with AND, and the exports take the same
# parameters. The production reports (schema/golden/production/reports.json)
# span four chips, three days and six tester versions.
class FiltersTest < ActionDispatch::IntegrationTest
  PRODUCTION = JSON.parse(ReportSchema.dir.join("golden", "production", "reports.json").read).fetch("reports")
  M3 = "xHGd4Toq7io8CSHYYFhTjZBD"
  M1_AIR_BUILD = "0052582.362956774610001"
  M1_AIR_SET = "apple-test-0052582276d9-20260927"

  setup do
    PRODUCTION.each do |entry|
      report = Report.create!(body: entry["report"].except("signature"), schema_version: entry["report"]["schema_version"],
                              machine_id: "key:machine-#{entry["id"]}", created_at: Time.iso8601(entry["uploaded_at"]))
      report.update_columns(public_id: entry["id"])
    end
  end

  def listed(params = {})
    get "/reports", params: params
    assert_response :success
    css_select("tr.report-row").map { |row| row["id"].delete_prefix("report-") }
  end

  def m2_boards = PRODUCTION.select { |e| e["report"]["machine"]["chip"].start_with?("M2") }.map { |e| e["report"]["machine"]["board"] }.uniq.sort

  def count = css_select(".filter-count").sole["data-count"].to_i

  def ids_where(&block) = PRODUCTION.select { |entry| block.call(entry["report"], entry) }.map { |entry| entry["id"] }.sort

  def parse_csv(text)
    text.split("\r\n").map { |line| line.scan(/"((?:[^"]|"")*)"/).flatten.map { |field| field.gsub('""', '"') } }
  end

  test "every run filter narrows the reports list, and the count says how many match" do
    assert_equal PRODUCTION.size, listed.size
    assert_equal PRODUCTION.size, count
    assert_select ".filter-chip", 0
    assert_select ".filter-clear", 0

    assert_equal ids_where { |r| r["machine"]["chip"] == "M1 Pro" }, listed(chip: "M1 Pro").sort
    assert_equal 4, count
    assert_equal ids_where { |r| r["machine"]["chip"].start_with?("M1") }, listed(gen: "m1").sort
    assert_equal 6, count
    assert_equal ids_where { |r| r["machine"]["soc"] == "t6021" }, listed(soc: "t6021").sort
    assert_equal ids_where { |r| r["machine"]["board"] == "j613" }, listed(model: "j613").sort
    assert_equal [ M3 ], listed(gen: "M3")
    assert_equal ids_where { |r| r["tool"]["version"] == "0.1.8" }, listed(tool: "0.1.8").sort
    assert_equal 4, count
    assert_equal ids_where { |r| r["system"]["stack"] == "converged" }, listed(stack: "converged").sort
    assert_equal [], listed(stack: "mx-mac")
    assert_equal PRODUCTION.size, listed(release: "4.0.0").size
    assert_equal [], listed(release: "4.1.0")
    assert_select ".dim", /No reports match these filters yet/
    assert_equal ids_where { |r| Report.new(body: r).build&.id == M1_AIR_BUILD }, listed(build: M1_AIR_BUILD).sort
    assert_equal listed(build: M1_AIR_BUILD).sort, listed(set: M1_AIR_SET).sort
    assert_equal 4, count
  end

  test "the upload date range takes whole UTC days, each end included" do
    assert_equal ids_where { |_, e| e["uploaded_at"].start_with?("2026-09-27") }, listed(from: "2026-09-27", to: "2026-09-27").sort
    assert_equal 7, count
    assert_equal [ M3 ], listed(from: "2026-09-28")
    assert_equal ids_where { |_, e| e["uploaded_at"] < "2026-09-27" }, listed(to: "2026-09-26").sort
    # A malformed date is dropped, not an error.
    assert_equal PRODUCTION.size, listed(from: "yesterday", to: "2026-02-31").size
    assert_select ".filter-chip", 0
  end

  test "tester runs only, or community runs only" do
    Tester.find_or_create_by!(login: "maralcbr")
    Report.where(public_id: [ M3, PRODUCTION.find { |e| e["id"].start_with?("Gbu7hc") }["id"] ]).update_all(tester_login: "maralcbr")

    assert_equal 2, listed(runs: "tester").size
    assert_select "tr.report-row .badge-tester", 2
    assert_equal PRODUCTION.size - 2, listed(runs: "community").size
    assert_select "tr.report-row .badge-tester", 0
    assert_equal PRODUCTION.size, listed(runs: "all").size
  end

  test "filters combine with AND, show as removable chips, and clear goes back to everything" do
    ids = listed(gen: "m1", tool: "0.1.8", from: "2026-09-27")
    assert_equal ids_where { |r, e| r["machine"]["chip"].start_with?("M1") && r["tool"]["version"] == "0.1.8" && e["uploaded_at"] >= "2026-09-27" }, ids.sort
    assert_equal 2, count
    chips = css_select(".filter-chip").to_h { |chip| [ chip["data-filter"], chip ] }
    assert_equal %w[gen tool from], chips.keys
    assert_match "generation: M1", chips["gen"].text
    assert_match "tester version: 0.1.8", chips["tool"].text
    # Each chip links to the same view without it.
    assert_equal "/reports?from=2026-09-27&tool=0.1.8", chips["gen"]["href"]
    assert_select ".filter-clear[href=?]", "/reports"
    # The form shows what's picked, so submitting it again keeps the filters.
    assert_select %(form.filter-bar[method="get"][action="/reports"])
    assert_select %(select[name="gen"] option[selected][value="m1"])
    assert_select %(select[name="tool"] option[selected][value="0.1.8"])
    assert_select %(input[name="from"][value="2026-09-27"])
    # A filter that matches nothing keeps its chip, with none of the runs.
    assert_equal [], listed(gen: "m1", chip: "M2 Max")
    assert_equal 0, count
  end

  test "an unknown value matches nothing, and a value past the choices still shows as picked" do
    assert_equal [], listed(model: "j999")
    assert_select %(select[name="model"] option[selected][value="j999"])
    assert_equal [], listed(tool: "9.9.9")
    # Values that aren't a choice are dropped: the view is unfiltered.
    assert_equal PRODUCTION.size, listed(stack: "bogus", runs: "someone", gen: "m9", confirmed: "yes").size
    assert_select ".filter-chip", 0
  end

  test "confirmed only leaves the answers given by a bare Enter out of the counts" do
    m3 = PRODUCTION.find { |entry| entry["id"] == M3 }["report"]
    by_default = m3["checks"].count { |check| check["answered_by_default"] }
    assert by_default.positive?

    listed
    all = css_select("tr#report-#{M3} td.nowrap").last.text[/(\d+) pass/, 1].to_i
    assert_equal PRODUCTION.size, listed(confirmed: "1").size
    assert_select %(.filter-chip[data-filter="confirmed"]), /results: confirmed only/
    confirmed = css_select("tr#report-#{M3} td.nowrap").last.text[/(\d+) pass/, 1].to_i
    assert_equal by_default, all - confirmed
  end

  test "the matrix takes every run filter, with the count of runs behind it" do
    get "/matrix", params: { gen: "m1" }
    assert_equal 6, count
    m1_boards = PRODUCTION.select { |e| e["report"]["machine"]["chip"].start_with?("M1") }.map { |e| e["report"]["machine"]["board"] }.uniq.sort
    assert_equal m1_boards, css_select("tr.matrix-row").map { |row| row["data-board"] }.uniq.sort

    get "/matrix", params: { chip: "M3", tool: "0.1.8", to: "2026-09-28" }
    assert_equal [ "j613" ], css_select("tr.matrix-row").map { |row| row["data-board"] }
    assert_equal 1, count

    get "/matrix", params: { from: "2026-09-29" }
    assert_select "tr.matrix-row", 0
    assert_select ".card .dim", /No reports match these filters yet/
  end

  test "the matrix's layer filter keeps one layer's columns" do
    get "/matrix", params: { layer: "aurora" }
    layers = css_select("th.feature-head").map { |th| th["class"][/layer-(\w+)/, 1] }.uniq
    assert_equal [ "aurora" ], layers
    assert_equal Catalogue.tested_features.count { |f| f["layer"] == "aurora" }, css_select("th.feature-head").size
    assert_select %(.filter-chip[data-filter="layer"]), /layer: Aurora addition/
  end

  test "the matrix's state filter keeps the rows and columns with a cell in that state" do
    %w[works fails gap untested].each do |state|
      get "/matrix", params: { state: }
      wanted = ReportFilter::STATES.fetch(state)
      rows = css_select("tr.matrix-row")
      rows.each do |row|
        displayed = row.css("td[data-feature]").map { |td| td["class"][/cell-hint-([\w-]+)/, 1] || td["data-state"] }
        assert (displayed & wanted).any?, "every #{state} row has a #{state} cell"
      end
      columns = css_select("th.feature-head").size
      css_select("th.feature-head").each_with_index do |_, index|
        column = rows.map { |row| row.css("td[data-feature]")[index] }
        assert column.any? { |td| wanted.include?(td["class"][/cell-hint-([\w-]+)/, 1] || td["data-state"]) }, "every #{state} column has a #{state} cell"
      end
      assert columns <= Catalogue.tested_features.size
    end
  end

  test "confirmed only hides the matrix cells community machines don't agree on" do
    get "/matrix"
    all = css_select("tr.matrix-row").size
    assert css_select(%(td[data-state="unconfirmed"])).any?, "most production runs are the only machine on their build: unconfirmed"
    assert_includes css_select("tr.matrix-row").map { |row| row["data-board"] }, "j613"

    get "/matrix", params: { confirmed: "1" }
    assert_select %(td[data-state="unconfirmed"]), 0
    assert css_select(%(td[data-state="hidden"].cell-hidden)).any?
    rows = css_select("tr.matrix-row")
    assert rows.size < all
    rows.each { |row| assert row.css("td[data-feature]").any? { |td| !%w[hidden not-tested].include?(td["data-state"]) } }
    # The M3 is the only machine on its build: nothing it found is confirmed.
    assert_not_includes rows.map { |row| row["data-board"] }, "j613"

    # A tester run colours cells on its own, so its row comes back.
    Tester.find_or_create_by!(login: "maralcbr")
    Report.find_by!(public_id: M3).update_columns(tester_login: "maralcbr")
    get "/matrix", params: { confirmed: "1" }
    assert css_select(%(tr.matrix-row[data-board="j613"] td[data-verified="tester"])).any?
  end

  test "the old matrix and reports links keep working, and keep the other filters" do
    get "/matrix", params: { build: M1_AIR_BUILD }
    assert_equal [ M1_AIR_BUILD ], css_select("tr.matrix-row").map { |row| row["data-build"] }.uniq
    assert_select %(.filter-chip[data-filter="build"])

    get "/matrix", params: { group: "release", gen: "m2" }
    assert_equal [ "" ], css_select("tr.matrix-row").map { |row| row["data-build"].to_s }.uniq
    assert_equal m2_boards, css_select("tr.matrix-row").map { |row| row["data-board"] }.uniq.sort
    # group stays through the form, the chips and clear.
    assert_select %(form.filter-bar input[type="hidden"][name="group"][value="release"])
    assert_select ".filter-chip[href=?]", "/matrix?group=release"
    assert_select ".filter-clear[href=?]", "/matrix?group=release"
    # The build links keep the other filters.
    assert_select "#build-filters a[href=?]", "/matrix?gen=m2"
    assert(css_select("#build-filters a[data-build]").all? { |a| a["href"].include?("gen=m2") })
    assert_empty css_select("#build-filters a[data-build]").map { |a| a["data-build"] } - %w[1937418.362376005140001]

    assert_equal ids_where { |r| Report.new(body: r).build&.id == M1_AIR_BUILD }, listed(build: M1_AIR_BUILD).sort
  end

  test "the reports exports take the filters, and without any are unchanged" do
    get "/api/v1/reports.json"
    body = response.parsed_body
    assert_not body.key?("filters")
    assert_equal PRODUCTION.size, body["reports"].size

    get "/api/v1/reports.json", params: { gen: "m1", tool: "0.1.8" }
    body = response.parsed_body
    assert_equal({ "gen" => "m1", "tool" => "0.1.8" }, body["filters"])
    assert_equal ids_where { |r| r["machine"]["chip"].start_with?("M1") && r["tool"]["version"] == "0.1.8" }, body["reports"].map { |r| r["id"] }.sort

    get "/api/v1/reports.csv", params: { chip: "M2 Max", from: "2026-09-27" }
    rows = parse_csv(response.body)
    assert_equal DataExport::REPORT_COLUMNS, rows.first
    assert_equal ids_where { |r, e| r["machine"]["chip"] == "M2 Max" && e["uploaded_at"] >= "2026-09-27" }, rows.drop(1).map(&:first).sort

    # Confirmed only counts the checks without those answered by a bare Enter.
    m3 = PRODUCTION.find { |entry| entry["id"] == M3 }["report"]
    get "/api/v1/reports.csv", params: { model: "j613", confirmed: "1" }
    row = parse_csv(response.body).drop(1).sole
    assert_equal (m3["checks"].size - m3["checks"].count { |c| c["answered_by_default"] }).to_s, row[DataExport::REPORT_COLUMNS.index("checks")]
  end

  test "checks.csv takes the run filters and the result filters" do
    get "/api/v1/checks.csv"
    all = parse_csv(response.body).drop(1)
    column = ->(name) { DataExport::CHECK_COLUMNS.index(name) }

    get "/api/v1/checks.csv", params: { model: "j613" }
    m3 = parse_csv(response.body).drop(1)
    assert_equal all.select { |row| row[column["board"]] == "j613" }, m3

    get "/api/v1/checks.csv", params: { model: "j613", layer: "aurora" }
    assert_equal m3.select { |row| row[column["layer"]] == "aurora" }, parse_csv(response.body).drop(1)

    get "/api/v1/checks.csv", params: { model: "j613", confirmed: "1" }
    assert_equal m3.reject { |row| row[column["answered_by_default"]] == "true" }, parse_csv(response.body).drop(1)

    get "/api/v1/checks.csv", params: { model: "j613", state: "gap" }
    gaps = parse_csv(response.body).drop(1)
    assert gaps.any?
    assert(gaps.all? { |row| %w[not-in-aurora not-in-asahi not-in-omarchy].include?(row[column["outcome"]]) })

    get "/api/v1/checks.csv", params: { model: "j613", state: "works", layer: "omarchy", confirmed: "1" }
    rows = parse_csv(response.body).drop(1)
    assert(rows.all? { |row| row[column["outcome"]] == "works" && row[column["layer"]] == "omarchy" && row[column["answered_by_default"]] == "false" })
  end

  test "matrix.json takes the filters and ?group=release, and without any is unchanged" do
    get "/api/v1/matrix.json"
    plain = response.parsed_body
    assert_not plain.key?("filters")
    assert_equal Catalogue.tested_features.size, plain["features"].size

    get "/api/v1/matrix.json", params: { gen: "m2", layer: "asahi" }
    body = response.parsed_body
    assert_equal({ "gen" => "m2", "layer" => "asahi" }, body["filters"])
    assert_equal 4, body["runs"]
    assert_equal m2_boards, body["rows"].map { |row| row["board"] }.uniq.sort
    assert_equal [ "asahi" ], body["features"].map { |f| f["layer"] }.uniq
    assert_equal body["features"].map { |f| f["id"] }.sort, body["rows"].first["cells"].keys.sort

    get "/api/v1/matrix.json", params: { gen: "m2", group: "release" }
    assert_equal m2_boards.size, response.parsed_body["rows"].size

    get "/api/v1/matrix.json", params: { confirmed: "1" }
    cells = response.parsed_body["rows"].flat_map { |row| row["cells"].values }
    assert(cells.none? { |cell| cell["state"].nil? && !cell["hidden"] })
    assert(cells.any? { |cell| cell["hidden"] })
  end

  test "the pages link the exports with the same filters" do
    get "/reports", params: { gen: "m1" }
    assert_select ".filter-exports a[href=?]", "/api/v1/reports.json?gen=m1"
    assert_select ".filter-exports a[href=?]", "/api/v1/reports.csv?gen=m1"
    assert_select ".filter-exports a[href=?]", "/api/v1/checks.csv?gen=m1"

    get "/matrix", params: { gen: "m1", layer: "aurora", group: "release" }
    assert_select ".filter-exports a[href=?]", "/api/v1/matrix.json?gen=m1&group=release&layer=aurora"
    assert_select ".filter-exports a[href=?]", "/api/v1/checks.csv?gen=m1&layer=aurora"
  end
end
