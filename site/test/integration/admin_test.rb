require "test_helper"

# Seam B: the admin, signed in with GitHub, hides, shows and deletes any
# report. (Until GitHub sign-in is set up, the v0.1 ADMIN_TOKEN: AdminTokenTest.)
class AdminTest < ActionDispatch::IntegrationTest
  def sign_in(login = "maralcbr") = sign_in_admin_with_github(login)

  setup do
    configure_github
    @m2 = upload_report golden("m2-max-image2"), machine: "a"
    @other = upload_report golden("m2-max-image2"), machine: "b"
  end

  test "without GitHub sign-in or ADMIN_TOKEN there is no admin" do
    ENV.delete("GITHUB_CLIENT_SECRET")

    get "/admin"
    assert_response :not_found
    post "/admin/session"
    assert_response :not_found
    get "/auth/github/callback", params: { code: "x", state: "y" }
    assert_response :not_found
  end

  test "sign-in goes to GitHub with only the client ID and a one-time state, and back to the callback" do
    get "/admin"
    assert_response :unauthorized
    assert_select "form[action='/admin/session'] button", "Sign in with GitHub"
    assert_select "input[type=password]", 0

    post "/admin/session"
    location = URI(response.location)
    assert_equal "https://github.com/login/oauth/authorize", "#{location.scheme}://#{location.host}#{location.path}"
    query = Rack::Utils.parse_query(location.query)
    assert_equal [ "Ov23test", "http://www.example.com/auth/github/callback", "" ], query.values_at("client_id", "redirect_uri", "scope")
    assert_not_includes location.query, "test-secret"
    assert_operator query["state"].size, :>=, 32
  end

  test "an admin handle signs in; the callback's redirect_uri matches the authorize one" do
    sign_in "MaralcBR"
    assert_redirected_to "/admin"
    assert_equal [ "http://www.example.com/auth/github/callback" ], github.exchanges
    get "/admin"
    assert_response :success
    assert_select ".subtitle", /signed in as @maralcbr/
  end

  test "a GitHub account that isn't an admin is refused" do
    sign_in "someone"
    assert_response :unauthorized
    assert_select ".flash-alert", "@someone isn't an admin of this site."
    get "/admin"
    assert_response :unauthorized
  end

  test "a callback with the wrong state, no state or a bad code signs nobody in" do
    post "/admin/session"
    github.codes["code"] = github.issue("token", "maralcbr")
    get "/auth/github/callback", params: { code: "code", state: "forged" }
    assert_response :unauthorized
    assert_select ".flash-alert", "That sign-in link is stale. Sign in again."

    get "/auth/github/callback", params: { code: "code" }
    assert_response :unauthorized

    post "/admin/session"
    state = Rack::Utils.parse_query(URI(response.location).query)["state"]
    get "/auth/github/callback", params: { code: "wrong", state: }
    assert_response :unauthorized
    assert_select ".flash-alert", /GitHub didn't sign you in/
    get "/admin"
    assert_response :unauthorized
  end

  test "the state works once" do
    post "/admin/session"
    state = Rack::Utils.parse_query(URI(response.location).query)["state"]
    github.codes["code"] = github.issue("token", "maralcbr")
    get "/auth/github/callback", params: { code: "code", state: }
    delete "/admin/session"

    github.codes["code"] = "token"
    get "/auth/github/callback", params: { code: "code", state: }
    assert_response :unauthorized
  end

  test "with GitHub sign-in set up, ADMIN_TOKEN no longer signs in" do
    ENV["ADMIN_TOKEN"] = "old-token"
    post "/admin/session", params: { token: "old-token" }
    assert_response :redirect
    assert_match %r{\Ahttps://github.com/}, response.location
    get "/admin"
    assert_response :unauthorized
  end

  test "taking a handle out of ADMIN_GITHUB_LOGINS signs it out" do
    sign_in
    ENV["ADMIN_GITHUB_LOGINS"] = "someone-else"

    get "/admin"
    assert_response :unauthorized
  end

  test "the admin lists every report and can hide one: it leaves the site and the matrix" do
    sign_in
    assert_redirected_to "/admin"
    get "/admin"
    assert_response :success
    assert_select "tr.admin-row", 2

    get "/matrix"
    assert_select %(td[data-feature="gpu"][data-state="works"])

    patch "/admin/reports/#{@m2["id"]}/hide"
    assert_redirected_to "/admin"
    assert Report.find_by!(public_id: @m2["id"]).hidden?
    get "/admin"
    assert_select "tr#admin-report-#{@m2["id"]} .badge", "hidden"

    get path_of(@m2["report_url"])
    assert_response :success, "the admin still sees a hidden report"
    assert_select ".badge", "hidden by the admin"

    delete "/admin/session"
    get path_of(@m2["report_url"])
    assert_response :not_found
    get "/reports"
    assert_select "tr.report-row", 1
    get "/matrix"
    assert_select %(td[data-feature="gpu"][data-state="unconfirmed"])
  end

  test "the admin can show a hidden report again" do
    Report.find_by!(public_id: @m2["id"]).update!(hidden_at: Time.current)
    sign_in

    patch "/admin/reports/#{@m2["id"]}/unhide"
    assert_redirected_to "/admin"
    delete "/admin/session"
    get path_of(@m2["report_url"])
    assert_response :success
  end

  test "the admin can delete any report" do
    sign_in

    delete "/admin/reports/#{@m2["id"]}"
    assert_redirected_to "/admin"
    assert_nil Report.find_by(public_id: @m2["id"])
    get path_of(@m2["report_url"])
    assert_response :not_found
  end

  test "nobody else can hide or delete" do
    patch "/admin/reports/#{@m2["id"]}/hide"
    assert_response :unauthorized
    delete "/admin/reports/#{@m2["id"]}"
    assert_response :unauthorized
    assert_equal 2, Report.visible.count
  end

  test "an admin session expires" do
    sign_in
    travel (AdminAuthentication::SESSION_HOURS.hours + 1.minute) do
      get "/admin"
      assert_response :unauthorized
    end
  end
end

# Seam B: until GitHub sign-in is set up, the v0.1 secret ADMIN_TOKEN signs
# the admin in, so a deploy never locks the admin out.
class AdminTokenTest < ActionDispatch::IntegrationTest
  TOKEN = "test-admin-token-#{SecureRandom.hex(8)}".freeze

  def sign_in(token = TOKEN) = post("/admin/session", params: { token: })

  setup do
    ENV["ADMIN_TOKEN"] = TOKEN
    @m2 = upload_report golden("m2-max-image2"), machine: "a"
  end

  test "without ADMIN_TOKEN there is no admin" do
    ENV.delete("ADMIN_TOKEN")

    get "/admin"
    assert_response :not_found
    sign_in ""
    assert_response :not_found
  end

  test "the token signs in" do
    sign_in
    assert_redirected_to "/admin"
    get "/admin"
    assert_response :success
  end

  test "the admin page asks for the token, and a wrong one is refused" do
    get "/admin"
    assert_response :unauthorized
    assert_select "input[type=password][name=token]"

    sign_in "wrong"
    assert_response :unauthorized
    assert_select ".flash-alert", "That token isn't right."
    get "/admin"
    assert_response :unauthorized
  end

  test "sign-in attempts are rate-limited" do
    10.times { sign_in "wrong" }
    sign_in
    assert_response :too_many_requests
    assert_select ".bad", "Too many attempts. Try again later."
    get "/admin"
    assert_response :unauthorized
  end

  test "changing ADMIN_TOKEN signs the admin out" do
    sign_in
    ENV["ADMIN_TOKEN"] = "#{TOKEN}-rotated"

    get "/admin"
    assert_response :unauthorized
    patch "/admin/reports/#{@m2["id"]}/hide"
    assert_response :unauthorized
  end
end
