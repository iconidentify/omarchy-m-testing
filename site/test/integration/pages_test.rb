require "test_helper"

# Seam B: the model, feature, kernel-gap and report pages, from golden reports.
class PagesTest < ActionDispatch::IntegrationTest
  test "the models page lists each Mac with its stacks and report count" do
    upload_report golden("m2-max-image2")
    upload_report golden("m1-pro-mx-mac")

    get "/models"
    assert_response :success
    assert_select "tr#model-j416c td", "MacBook Pro (16-inch, M2 Max, 2023)"
    assert_select "tr#model-j416c td", "converged 4.0.0"
    assert_select "tr#model-j314s td", "mx-mac 4.0.2"
  end

  test "a model page shows what its chip is expected to do and each stack's results" do
    upload_report golden("m2-max-image2"), machine: "a"
    upload_report golden("m2-max-image2"), machine: "b"

    get "/models/j416c"
    assert_response :success
    assert_select "h1", "MacBook Pro (16-inch, M2 Max, 2023)"
    assert_select ".subtitle", /M2 Pro\/Max\/Ultra generation · SoC t6021 · board j416c/
    assert_equal [ "–", "supported 7.1.12", "–" ], css_select("tr#feature-aop td.expected").map(&:text)
    assert_select "tr#feature-gpu td.expected.expected-yes", "linux-asahi"
    assert_select %(tr#feature-gpu td[data-state="works"])
    assert_select "th.config-head", "converged 4.0.0"
    assert_select "tr.report-row", 2
    assert_select ".credit", /CC BY 3\.0/
  end

  test "a model without visible reports is not found" do
    get "/models/j999"
    assert_response :not_found
  end

  test "the features page lists the catalogue by layer, with results where tested" do
    upload_report golden("m2-max-image2")

    get "/features"
    assert_response :success
    assert_select "#layer-asahi .card-title", "asahi hardware"
    assert_select "#layer-aurora tr#feature-usb4-displays"
    assert_select "#layer-omarchy tr#feature-notch-bar .chip-result.cell-unconfirmed"
    assert_select "tr.feature-row", Catalogue.features.size
    assert_select ".credit", /CC BY 3\.0/
  end

  test "a feature page shows per-chip expectations and results per Mac" do
    upload_report golden("m2-max-image2"), machine: "a"
    upload_report golden("m2-max-image2"), machine: "b"
    upload_report golden("m1-pro-mx-mac")

    get "/features/first-boot-hardware-setup"
    assert_response :success
    assert_select "h1", "First-boot hardware setup"
    assert_select "tr.result-row", 2
    assert_select %(tr.result-row[data-board="j416c"] td[data-state="partial"])
    assert_select %(tr.result-row[data-board="j416c"] .summary), "partial: 2 machines partial"
    assert_select %(tr.result-row[data-board="j314s"] td[data-state="unconfirmed"])
    assert_equal [ "–", "supported 7.1.12", "supported" ], css_select("tr#chip-m2-pro-max-ultra td.expected").map(&:text)
    assert_select "code", "setup.first-boot-hardware"
  end

  test "a feature no check covers says so" do
    get "/features/touch-id"
    assert_response :success
    assert_select ".card", /no check covers it/
    assert_select "tr#chip-m1 td.expected-none"
  end

  test "an unknown feature is not found" do
    get "/features/warp-drive"
    assert_response :not_found
  end

  test "the kernel-gap list shows reported gaps and what Asahi has but Aurora hasn't verified" do
    report = golden_with("m2-max-image2", "input.ambient-light" => "not-in-aurora", "display.outputs" => "not-in-asahi",
                                          "power.battery" => "unknown-hardware")
    upload_report report
    upload_report golden("m1-pro-mx-mac")

    get "/gaps"
    assert_response :success
    assert_select %(#reported tr.gap-row[data-outcome="not-in-aurora"][data-feature="aop"] td), /M2 Max/
    assert_select %(#reported tr.gap-row[data-outcome="not-in-asahi"][data-feature="main-display"])
    assert_select %(#reported tr.gap-row[data-outcome="unknown-hardware"][data-feature="battery-info"] a[href^="/reports/"])
    assert_select %(#reported tr.gap-row[data-outcome="not-in-aurora"][data-feature="hardware-drivers"]), 2 # both Macs' unclaimed hardware
    assert_select "#reported tr.gap-row", 5
    assert_select %(#unverified-in-aurora tr.gap-row[data-feature="video-decoder"] td), /M3/
    assert_select "#missing-in-aurora", /nothing Asahi supports that Aurora is known to lack/
    assert_select ".credit", /CC BY 3\.0/
  end

  test "the reports page lists every visible report, newest first" do
    first = upload_report golden("m1-pro-mx-mac")
    second = upload_report golden("m2-max-image2")

    get "/reports"
    assert_response :success
    assert_equal [ second["id"], first["id"] ].map { |id| "report-#{id}" }, css_select("tr.report-row").map { |row| row["id"] }
    assert_select "tr#report-#{second["id"]} td", "converged 4.0.0"
    assert_select "tr#report-#{second["id"]} td", /32 pass 4 fail 7 skip/
  end

  test "the report page reads like terminal output, grouped by section" do
    body = upload_report golden("m2-max-image2")
    get path_of(body["report_url"])

    assert_select ".terminal .terminal-bar", /omarchy-m-test/
    assert_select ".terminal .badge-community", "community report"
    # One title per check-id prefix, plus the hardware inventory.
    assert_select "h2.section-title", %w[system boot packages setup hardware gpu display audio network input power cpu].size + 1
    assert_select "dd", "converged 4.0.0"
    assert_select "dd", "omarchy, limine, encryption on"
    assert_select "li#check-setup\\.first-boot-hardware .status.status-fail", "FAIL"
    assert_select "li#check-setup\\.first-boot-hardware .badge-regression", "doesn't work, but should on this Mac"
    assert_select ".packages summary", "packages (13)"
  end
end
