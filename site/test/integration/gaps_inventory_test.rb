require "test_helper"

# Seam B: the kernel-gap page's unclaimed hardware, from the golden reports' inventory.
class GapsInventoryTest < ActionDispatch::IntegrationTest
  def row(compatible) = %(#unclaimed-hardware tr.unclaimed-row[data-compatible="#{compatible}"])

  test "the kernel-gap page lists hardware no driver claims, unknown hardware first" do
    upload_report golden("m2-max-image2"), ip: "10.0.0.1"
    upload_report golden("m2-max-image2"), ip: "10.0.0.2"
    upload_report golden("m1-pro-mx-mac"), ip: "10.0.0.3"

    get "/gaps"
    assert_response :success
    assert_equal %w[apple,t6000-dpaudio apple,t6020-dpaudio apple,t6020-avd],
                 css_select("#unclaimed-hardware tr.unclaimed-row").map { |tr| tr["data-compatible"] }
    assert_select "#{row("apple,t6020-dpaudio")}[data-outcome=unknown-hardware] td", "unknown hardware"
    assert_select "#{row("apple,t6020-dpaudio")} td", "M2 Max (t6021)"
    assert_select "#{row("apple,t6020-dpaudio")} td", "MacBook Pro (16-inch, M2 Max, 2023)"
    assert_select "#{row("apple,t6020-dpaudio")} td.machines", "2"
    assert_select "#{row("apple,t6000-dpaudio")} td.machines", "1"
    assert_select "#{row("apple,t6000-dpaudio")} td", "MacBook Pro (14-inch, M1 Pro, 2021)"
    # Hardware the catalogue knows links to its feature.
    assert_select "#{row("apple,t6020-avd")}[data-outcome=fails] td a[href=?]", "/features/video-decoder", "Video decoder"
    assert_select "#{row("apple,t6020-avd")} td a[href^='/reports/']", 2
    assert_no_match(/once reports carry/, response.body)
  end

  test "reports without an inventory add nothing" do
    upload_report golden("m2-max-image2").tap { |report| report.delete("inventory") }

    get "/gaps"
    assert_response :success
    assert_select "#unclaimed-hardware tr.unclaimed-row", 0
    assert_select "#unclaimed-hardware", /None reported/
  end
end
