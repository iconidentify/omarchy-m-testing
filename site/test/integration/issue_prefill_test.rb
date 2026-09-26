require "test_helper"

# Seam B: the admin opens a prefilled GitHub issue from any failure or gap,
# on omacom/linux (Asahi hardware, Aurora additions) or omacom/omarchy-mac
# (Omarchy integration). The site only builds the link; it never calls GitHub.
class IssuePrefillTest < ActionDispatch::IntegrationTest
  TOKEN = "test-admin-token-#{SecureRandom.hex(8)}".freeze

  setup do
    ENV["ADMIN_TOKEN"] = TOKEN
    Tester.create!(login: "tester-one")
    bind_machine "t", "tester-one"
  end

  def sign_in = post("/admin/session", params: { token: TOKEN })

  # An issue link's target repo, title and body.
  def issue(link)
    uri = URI(link["href"])
    assert_equal [ "https", "github.com" ], [ uri.scheme, uri.host ]
    query = Rack::Utils.parse_query(uri.query)
    [ uri.path.delete_suffix("/issues/new").delete_prefix("/"), query.fetch("title"), query.fetch("body") ]
  end

  def issue_in(selector) = issue(css_select("#{selector} a.issue-link").sole)

  test "visitors see no issue links" do
    uploaded = upload_report golden("m2-max-image2")
    get path_of(uploaded["report_url"])
    assert_select "a.issue-link", 0
    get "/gaps"
    assert_select "a.issue-link", 0
  end

  test "a failing check's issue goes to its layer's project, with the report, the Mac and the evidence" do
    uploaded = upload_report golden_with("m2-max-image2", "gpu.driver" => "fails")
    sign_in
    get path_of(uploaded["report_url"])

    repo, title, body = issue_in("li#check-setup\\.first-boot-hardware")
    assert_equal "omacom/omarchy-mac", repo
    assert_equal "First-boot hardware setup: doesn't work, but should on this Mac · MacBook Pro (16-inch, M2 Max, 2023), converged 4.0.0", title
    assert_includes body, "Report: #{uploaded["report_url"]}"
    assert_includes body, "Apple MacBook Pro (16-inch, M2 Max, 2023), M2 Max (t6021, board j416c)"
    assert_includes body, "- Kernel: 7.1.12-2-2-ARCH, linux-aurora 7.1.12.aurora2-2"
    assert_includes body, "- Expected: aurora supported, omarchy supported"
    assert_includes body, "```text\n2026-09-26T08:37:37+10:00 <hostname> omarchy-provision-hardware"
    assert_equal "_blank", css_select("li#check-setup\\.first-boot-hardware a.issue-link").sole["target"]

    repo, title, = issue_in("li#check-gpu\\.driver")
    assert_equal "omacom/linux", repo, "the Asahi hardware layer goes to the Aurora kernel"
    assert_match(/\AGPU: /, title)
    assert_select "li#check-gpu\\.vulkan a.issue-link", 0, "no issue for what works"
  end

  test "a regression's issue says so and links the last verified pass" do
    pass = upload_report golden("m2-max-image2"), machine: "t"
    failing = upload_report golden_with("m2-max-image2", "gpu.driver" => "fails", "gpu.vulkan" => "fails"), machine: "a"
    sign_in

    get path_of(failing["report_url"])
    repo, title, body = issue_in("li#check-gpu\\.driver")
    assert_equal "omacom/linux", repo
    assert_equal "Regression: GPU · MacBook Pro (16-inch, M2 Max, 2023), converged 4.0.0", title
    assert_includes body, "Last verified pass on the same model and stack: #{pass["report_url"]}"

    get "/gaps"
    repo, title, body = issue_in(%(#regressions tr.regression-row[data-feature="gpu"]))
    assert_equal [ "omacom/linux", "Regression: GPU · MacBook Pro (16-inch, M2 Max, 2023), converged 4.0.0" ], [ repo, title ]
    assert_includes body, "Last verified pass: #{pass["report_url"]}"
    assert_includes body, "Runs with the regression:\n- #{failing["report_url"]}"
  end

  test "every gap on the kernel-gap page has one" do
    uploaded = upload_report golden_with("m2-max-image2", "input.ambient-light" => "not-in-aurora")
    sign_in
    get "/gaps"

    repo, title, body = issue_in(%(tr.gap-row[data-outcome="not-in-aurora"][data-feature="aop"]))
    assert_equal "omacom/linux", repo
    assert_equal "Always-on processor (AOP: ambient light sensor, lid angle): not yet supported by Aurora on M2 Max", title
    assert_includes body, "Reports:\n- #{uploaded["report_url"]}"

    repo, title, body = issue_in(%(tr.unclaimed-row[data-compatible="apple,t6020-avd"]))
    assert_equal [ "omacom/linux", "No driver claims apple,t6020-avd on M2 Max" ], [ repo, title ]
    assert_includes body, uploaded["report_url"]

    catalogue_gaps = css_select("#unverified-in-aurora tr.gap-row")
    assert catalogue_gaps.any?
    repo, title, body = issue(catalogue_gaps.first.at_css("a.issue-link"))
    assert_equal "omacom/linux", repo
    assert_match(/: verify Aurora on /, title)
    assert_includes body, "Feature page: http://www.example.com/features/"
  end

  test "hidden reports get no issue, and long evidence is cut short with its fence closed" do
    long = golden("m2-max-image2").tap do |report|
      report["checks"].find { |check| check["id"] == "setup.first-boot-hardware" }["evidence"] = Array.new(50) { |i| "line #{i} " + ("x" * 400) }
    end
    uploaded = upload_report long
    sign_in
    get path_of(uploaded["report_url"])
    _, _, body = issue_in("li#check-setup\\.first-boot-hardware")
    assert_operator body.size, :<, IssueDraft::MAX_BODY + 100
    assert_includes body, "Report: #{uploaded["report_url"]}", "the report link comes before the evidence"
    assert body.scan("```").size.even?
    assert_match(/cut short/, body)

    Report.update_all(hidden_at: Time.current)
    get path_of(uploaded["report_url"])
    assert_response :success
    assert_select "a.issue-link", 0
  end
end
