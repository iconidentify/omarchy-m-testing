require "test_helper"

# Seam B: omarchy-m-test --sign-in. The CLI sends the golden sign-in (a GitHub
# token, signed by its machine key); the site checks with GitHub that this
# app issued the token, binds the handle to the machine key and revokes the
# token. That machine's later runs are tester runs while the handle is on the
# allowlist.
class TesterSignInTest < ActionDispatch::IntegrationTest
  FIXTURE_MACHINE_REPORT = -> { File.read(GoldenReports.signed_paths.find { |path| path.end_with?("/m2-max-image2.json") }) }

  setup do
    configure_github
    Tester.create!(login: "maralcbr")
    github.issue(GoldenSignIn::TOKEN, "MaralcBR", id: 4242)
  end

  test "the golden sign-in binds the GitHub handle to the machine key, and the token is revoked, never kept" do
    body = sign_in_tester

    assert_response :created
    assert_equal({ "login" => "MaralcBR", "tester" => true }, body.slice("login", "tester"))
    assert_match "This Mac's runs now count as tester runs", body["message"]
    binding = TesterBinding.sole
    assert_equal [ "maralcbr", 4242 ], [ binding.github_login, binding.github_id ]
    assert_equal [ GoldenSignIn::TOKEN ], github.revoked
    assert_not TesterBinding.column_names.any? { |column| column.include?("token") }

    upload_report FIXTURE_MACHINE_REPORT.call
    assert_response :created
    assert_equal binding.machine_id, Report.sole.machine_id, "the sign-in and the reports are signed by the same machine key"
  end

  test "after signing in, the machine's runs are tester runs: the upload says so and the report has the tester badge" do
    upload_report FIXTURE_MACHINE_REPORT.call
    before = Report.sole
    sign_in_tester

    uploaded = upload_report FIXTURE_MACHINE_REPORT.call
    assert_equal true, uploaded["tester"]
    get path_of(uploaded["report_url"])
    assert_select ".report-badges .badge-tester", "tester run"
    assert_select ".report-badges", text: /maralcbr/i, count: 0

    get path_of(report_url(before))
    assert_select ".report-badges .badge-community", "community report"
    get "/reports"
    assert_select "tr.report-row .badge-tester", 1
    assert_select "tr.report-row .badge-community", 1
  end

  test "a handle that isn't on the allowlist is bound, but its runs stay community runs until the admin adds it" do
    Tester.delete_all
    body = sign_in_tester
    assert_response :created
    assert_equal false, body["tester"]
    assert_match "isn't on the tester allowlist yet", body["message"]

    uploaded = upload_report FIXTURE_MACHINE_REPORT.call
    assert_equal false, uploaded["tester"]
    Tester.create!(login: "maralcbr")
    get path_of(uploaded["report_url"])
    assert_select ".report-badges .badge-tester", "tester run"
  end

  test "a token another app issued, or an unknown one, binds nothing" do
    github.app_tokens.clear
    github.other_tokens[GoldenSignIn::TOKEN] = Github::Identity.new(login: "maralcbr", id: 1)

    body = sign_in_tester
    assert_response :unauthorized
    assert_match "GitHub didn't confirm the sign-in", body["error"]
    assert_equal 0, TesterBinding.count
  end

  test "a sign-in changed after it was signed, or signed as a report, is refused" do
    forged = GoldenSignIn.json.merge("github_token" => "gho_someoneElsesToken")
    github.issue("gho_someoneElsesToken", "attacker")
    sign_in_tester forged
    assert_response :unprocessable_content
    assert_match "the report was changed after it was signed", response.parsed_body["error"]

    as_report = TestMachines.sign({ "binding_version" => 1, "github_token" => GoldenSignIn::TOKEN })
    sign_in_tester as_report
    assert_response :unprocessable_content
    assert_match "it isn't a sign-in signature (namespace)", response.parsed_body["error"]

    assert_equal 0, TesterBinding.count
    assert_empty github.revoked
  end

  test "anything but a sign-in is refused" do
    [ GoldenSignIn.json.except("signature"), GoldenSignIn.json.merge("extra" => 1), GoldenSignIn.json.merge("binding_version" => 2),
      GoldenSignIn.json.merge("signature" => "nope"), [ 1 ] ].each do |body|
      sign_in_tester body
      assert_response :unprocessable_content, body.inspect
    end
    sign_in_tester "{"
    assert_response :bad_request
    assert_equal 0, TesterBinding.count
  end

  test "without the GitHub app's secret there is no tester sign-in" do
    ENV.delete("GITHUB_CLIENT_SECRET")

    body = sign_in_tester
    assert_response :service_unavailable
    assert_equal "Tester sign-in isn't set up on this site yet.", body["error"]
  end

  test "signing in again on the machine rebinds it; earlier runs keep the handle they were uploaded under" do
    sign_in_tester
    upload_report FIXTURE_MACHINE_REPORT.call
    github.issue(GoldenSignIn::TOKEN, "someone-else", id: 7)

    sign_in_tester
    assert_equal "someone-else", TesterBinding.sole.github_login
    assert_equal "maralcbr", Report.sole.tester_login
  end

  test "an allowlisted handle is pinned to the first GitHub account that signs in with it" do
    sign_in_tester
    assert_equal 4242, Tester.find_by!(login: "maralcbr").github_id

    github.issue(GoldenSignIn::TOKEN, "maralcbr", id: 999) # the handle, renamed away and registered by someone else
    body = sign_in_tester
    assert_response :forbidden
    assert_match "a different GitHub account from the tester the admin added", body["error"]
    assert_equal 4242, TesterBinding.sole.github_id
  end

  test "an oversized sign-in is refused, also when sent chunked" do
    # Rack::Test always sets a Content-Length, so this goes to the app itself, as a chunked upload arrives.
    env = Rack::MockRequest.env_for("/api/v1/tester_bindings", method: "POST", input: GoldenSignIn.text + (" " * 9.kilobytes),
                                    "CONTENT_TYPE" => "application/json", "HTTP_TRANSFER_ENCODING" => "chunked", "REMOTE_ADDR" => "10.0.0.1")
    env.delete("CONTENT_LENGTH")
    status, = Rails.application.call(env)
    assert_equal 413, status
    assert_equal 0, TesterBinding.count
  end

  test "sign-ins are rate-limited per network" do
    Api::V1::TesterBindingsController::PER_HOUR.times { sign_in_tester "{" }
    sign_in_tester
    assert_response :too_many_requests
  end
end
