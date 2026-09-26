require "test_helper"

# Seam B: a failure is a regression only when a verified earlier run (a
# tester's) on the same Mac model and stack found the feature working;
# otherwise it's "doesn't work", so a user's setup error isn't mistaken for a
# regression.
class RegressionsTest < ActionDispatch::IntegrationTest
  M2 = "j416c".freeze
  GPU_FAILS = { "gpu.driver" => "fails", "gpu.vulkan" => "fails" }.freeze

  setup do
    Tester.create!(login: "tester-one")
    bind_machine "t", "tester-one"
  end

  def on_stack(report, stack) = report.tap { |r| r["system"]["stack"] = stack }
  def on_version(report, version) = report.tap { |r| r["system"]["packages"].find { |p| p["name"] == "omarchy" }["version"] = "#{version}-1" }

  # The golden report with every failing check working, then these outcomes.
  def working(name, outcomes = {})
    fixed = golden(name)["checks"].select { |check| check.dig("classification", "outcome") == "fails" }.to_h { |check| [ check["id"], "works" ] }
    golden_with(name, fixed.merge(outcomes))
  end

  def gpu_badges(uploaded)
    get path_of(uploaded["report_url"])
    css_select("li#check-gpu\\.driver .badge")
  end

  def matrix_gpu
    get "/api/v1/matrix.json"
    response.parsed_body["rows"].select { |row| row["board"] == M2 }.map { |row| row.dig("cells", "gpu", "tentative") }
  end

  test "a failure with no verified earlier pass is not a regression" do
    failing = upload_report golden_with("m2-max-image2", GPU_FAILS), machine: "a"

    assert_equal [ "doesn't work, but should on this Mac" ], gpu_badges(failing).map(&:text)
    assert_equal [ "fails" ], matrix_gpu
    get "/gaps"
    assert_select "#regressions tr.regression-row", 0
    assert_select "#regressions", /None open/
  end

  test "a failure after a tester's pass on the same model and stack is a regression, linked to that pass" do
    pass = upload_report golden("m2-max-image2"), machine: "t"
    failing = upload_report on_version(golden_with("m2-max-image2", GPU_FAILS), "4.1.0"), machine: "a"

    badge = gpu_badges(failing).find { |b| b["class"].include?("regression") }
    assert_equal "regression", badge.text
    assert_equal path_of(pass["report_url"]), badge["href"]
    assert_includes matrix_gpu, "regression", "the 4.1.0 row, across Omarchy versions"

    get "/gaps"
    row = css_select(%(#regressions tr.regression-row[data-feature="gpu"][data-board="#{M2}"][data-stack="converged"])).sole
    assert_equal path_of(pass["report_url"]), row.at_css("td.pass a")["href"]
    assert_match "converged 4.1.0", row.text
  end

  test "a community pass, a hidden tester pass or a removed tester's pass doesn't make it a regression" do
    upload_report golden("m2-max-image2"), machine: "b"
    failing = upload_report golden_with("m2-max-image2", GPU_FAILS), machine: "a"
    assert_not gpu_badges(failing).any? { |b| b.text == "regression" }, "community pass"

    upload_report golden("m2-max-image2"), machine: "t"
    Report.order(:id).last.update!(hidden_at: Time.current)
    later = upload_report golden_with("m2-max-image2", GPU_FAILS), machine: "a"
    assert_not gpu_badges(later).any? { |b| b.text == "regression" }, "hidden tester pass"

    Report.update_all(hidden_at: nil)
    assert gpu_badges(later).any? { |b| b.text == "regression" }
    Tester.find_by!(login: "tester-one").destroy!
    assert_not gpu_badges(later).any? { |b| b.text == "regression" }, "tester off the allowlist"
  end

  test "only the same model and stack, and only an earlier pass, count" do
    upload_report on_stack(golden("m2-max-image2"), "mx-mac"), machine: "t"
    other_stack = upload_report golden_with("m2-max-image2", GPU_FAILS), machine: "a"
    assert_not gpu_badges(other_stack).any? { |b| b.text == "regression" }, "a pass on mx-mac"

    other_model = upload_report golden_with("m1-pro-converged", GPU_FAILS), machine: "a"
    upload_report golden("m2-max-image2"), machine: "t"
    assert_not gpu_badges(other_model).any? { |b| b.text == "regression" }, "a pass on another Mac"
    assert_not gpu_badges(other_stack).any? { |b| b.text == "regression" }, "a pass uploaded after the failure"
  end

  test "a regression stays open until a newer run on that model and stack works again" do
    upload_report golden("m2-max-image2"), machine: "t"
    upload_report golden_with("m2-max-image2", GPU_FAILS), machine: "a"
    upload_report golden_with("m2-max-image2", GPU_FAILS), machine: "b"

    get "/gaps"
    assert_select %(#regressions tr.regression-row[data-feature="gpu"] td a[href^="/reports/"]), 3, "the pass and both runs with it"

    upload_report golden("m2-max-image2"), machine: "a"
    get "/gaps"
    assert_select %(#regressions tr.regression-row[data-feature="gpu"]), 0
  end

  test "two machines agreeing on a regression colour the cell red; the legend tells regressions from failures" do
    upload_report golden("m2-max-image2"), machine: "t"
    upload_report on_version(golden_with("m2-max-image2", GPU_FAILS), "4.1.0"), machine: "a"
    upload_report on_version(golden_with("m2-max-image2", GPU_FAILS), "4.1.0"), machine: "b"

    get "/matrix"
    gpu = css_select(%(tr.matrix-row[data-board="#{M2}"][data-version="4.1.0"] td[data-feature="gpu"])).sole
    assert_equal "regression", gpu["data-state"]
    assert_includes gpu["class"], "cell-regression"
    assert_equal "works", css_select(%(tr.matrix-row[data-board="#{M2}"][data-version="4.0.0"] td[data-feature="gpu"])).sole["data-state"]
    assert_select ".legend li", /regression/
    assert_select ".legend li", /doesn't work/
  end

  test "a tester's regression on a candidate set is named in the verdict" do
    upload_report working("m2-max-image2"), machine: "t"
    upload_report working("m2-max-image2", GPU_FAILS).tap { |r| r["system"]["candidate_set"] = "edge-1" }, machine: "t"

    get "/candidates/edge-1"
    assert_select %(#verdict[data-verdict="blocked"]), "Not ready: tester runs found 1 failure, 1 of them a regression"
    assert_select "#failures li.finding[data-state=regression]", /GPU/
  end
end
