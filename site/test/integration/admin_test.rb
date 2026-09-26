require "test_helper"

# Seam B: the v0.1 admin, signed in with the secret ADMIN_TOKEN, hides, shows
# and deletes any report.
class AdminTest < ActionDispatch::IntegrationTest
  TOKEN = "test-admin-token-#{SecureRandom.hex(8)}".freeze

  def sign_in(token = TOKEN) = post("/admin/session", params: { token: })

  setup do
    ENV["ADMIN_TOKEN"] = TOKEN
    @m2 = upload_report golden("m2-max-image2"), machine: "a"
    @other = upload_report golden("m2-max-image2"), machine: "b"
  end

  test "without ADMIN_TOKEN there is no admin" do
    ENV.delete("ADMIN_TOKEN")

    get "/admin"
    assert_response :not_found
    sign_in ""
    assert_response :not_found
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

  test "changing ADMIN_TOKEN signs the admin out" do
    sign_in
    ENV["ADMIN_TOKEN"] = "#{TOKEN}-rotated"

    get "/admin"
    assert_response :unauthorized
    patch "/admin/reports/#{@m2["id"]}/hide"
    assert_response :unauthorized
  end
end
