require "test_helper"

# Seam B: the Aurora feature-support table per chip generation, from
# tester-verified runs on the Aurora kernel only, with its sources.
class AuroraSupportTest < ActionDispatch::IntegrationTest
  M2_GEN = "m2-pro-max-ultra".freeze
  M1_GEN = "m1-pro-max-ultra".freeze

  setup do
    Tester.create!(login: "tester-one")
    Tester.create!(login: "tester-two")
  end

  def row(chip, feature) = css_select(%(tr.aurora-row[data-chip="#{chip}"][data-feature="#{feature}"])).sole

  test "community runs don't make the table" do
    upload_report golden("m2-max-image2"), machine: "a"
    upload_report golden("m2-max-image2"), machine: "b"

    get "/aurora"
    assert_response :success
    assert_select "tr.aurora-row", 0
    assert_select ".card", /No tester has uploaded a run on the Aurora kernel yet/
  end

  test "a tester's run on Aurora fills its chip generation, next to the expected states, with its sources" do
    bind_machine "a", "tester-one"
    uploaded = upload_report golden("m2-max-image2"), machine: "a"

    get "/aurora"
    assert_select "#chip-#{M2_GEN} .card-title", "M2 Pro/Max/Ultra"
    assert_select "#chip-#{M2_GEN}", /1 tester machine, 1 run: MacBook Pro \(16-inch, M2 Max, 2023\)/
    assert_select "#chip-#{M2_GEN}", /Aurora 7\.1\.12\.aurora2-2/
    gpu = row(M2_GEN, "gpu")
    assert_equal "works", gpu["data-state"]
    assert_equal "asahi", gpu.at_css("td.expected-yes").text, "Aurora expected to match linux-asahi"
    assert_equal path_of(uploaded["report_url"]), gpu.at_css("td.sources a")["href"]
    assert_match "7.1.12.aurora2-2", gpu.at_css("td.sources").text

    # Kernel features only: Omarchy integration isn't Aurora's.
    assert_select %(tr.aurora-row[data-feature="first-boot-hardware-setup"]), 0
    assert_select "tr.aurora-row[data-feature=aop]", 1
    # Chip generations nobody has verified yet are named, not guessed.
    assert_select "#untested-chips", /M1 Pro\/Max\/Ultra/
    assert_select "#sources", /Asahi Linux documentation/
    assert_select "#sources a[href='https://github.com/omacom/linux']"
    assert_select "nav a[href='/aurora']", "Aurora"
  end

  test "runs off the Aurora kernel don't count" do
    bind_machine "a", "tester-one"
    upload_report golden("m1-pro-mx-mac"), machine: "a"

    get "/aurora"
    assert_select "tr.aurora-row[data-chip=#{M1_GEN}]", 0
    assert_select "#untested-chips", /M1 Pro\/Max\/Ultra/
  end

  test "each tester machine counts once with its latest run; testers who disagree make it partial" do
    gpu_fails = { "gpu.driver" => "fails", "gpu.vulkan" => "fails" }
    bind_machine "a", "tester-one"
    bind_machine "b", "tester-two"
    upload_report golden_with("m2-max-image2", gpu_fails), machine: "a"
    upload_report golden("m2-max-image2"), machine: "a"
    upload_report golden("m2-max-converged"), machine: "b"

    get "/aurora"
    assert_equal "works", row(M2_GEN, "gpu")["data-state"]
    assert_select "#chip-#{M2_GEN}", /2 tester machines, 3 runs/

    upload_report golden_with("m2-max-converged", gpu_fails), machine: "b"
    get "/aurora"
    assert_equal "partial", row(M2_GEN, "gpu")["data-state"]
    assert_match "tester-verified", row(M2_GEN, "gpu").at_css("td.verified")["title"]
  end

  test "aurora.json has the table per chip, each cell's sources and the catalogue's sources" do
    bind_machine "a", "tester-one"
    uploaded = upload_report golden("m2-max-image2"), machine: "a"
    upload_report golden("m1-pro-converged"), machine: "c"

    get "/api/v1/aurora.json"
    assert_response :success
    body = response.parsed_body
    assert_equal "CC0-1.0", body.dig("license", "id")
    assert_equal Catalogue.version, body["catalogue_version"]
    assert_equal [ M2_GEN ], body["chips"].map { |chip| chip["chip"] }, "the community M1 run doesn't count"
    assert_includes body["untested_chips"], M1_GEN
    m2 = body["chips"].sole
    assert_equal [ "t6021" ], m2["socs"]
    assert_equal [ "7.1.12.aurora2-2" ], m2["aurora_versions"]
    gpu = m2.dig("cells", "gpu")
    assert_equal "works", gpu["state"]
    assert_equal({ "works" => 1 }, gpu["tester_machines"])
    assert_equal "asahi", gpu.dig("expected", "aurora", "status")
    assert_equal "linux-asahi", gpu.dig("expected", "asahi", "status")
    assert_equal [ uploaded["report_url"] ], gpu["reports"]
    assert_equal "CC-BY-3.0", body.dig("sources", "asahi", "license")
    assert_equal "https://github.com/omacom/linux", body.dig("sources", "aurora", "url")
    assert_not body["features"].any? { |feature| feature["layer"] == "omarchy" }

    get "/data"
    assert_select "a[href='/api/v1/aurora.json']", "aurora.json"
  end
end
