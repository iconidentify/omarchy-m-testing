require "test_helper"

# Seam B: the admin manages the tester allowlist and sees which machines
# signed in as whom.
class AdminTestersTest < ActionDispatch::IntegrationTest
  setup do
    configure_github
    Tester.create!(login: "maralcbr")
  end

  test "only the admin sees or changes the allowlist" do
    get "/admin/testers"
    assert_response :unauthorized
    post "/admin/testers", params: { tester: { login: "someone" } }
    assert_response :unauthorized
    delete "/admin/testers/maralcbr"
    assert_response :unauthorized
    assert_equal [ "maralcbr" ], Tester.pluck(:login)
  end

  test "the admin adds a handle, and that machine's runs become tester runs" do
    bind_machine "a", "new-tester"
    uploaded = upload_report golden("m2-max-image2"), machine: "a"
    sign_in_admin_with_github

    get "/admin/testers"
    assert_response :success
    assert_select "tr.tester-row", 1
    assert_select "tr.binding-row", 1
    assert_select "tr.binding-row .badge", "not on the allowlist"

    post "/admin/testers", params: { tester: { login: "@New-Tester" } }
    assert_redirected_to "/admin/testers"
    follow_redirect!
    assert_select ".flash-notice", "Added @new-tester to the testers."
    assert_select "tr#tester-new-tester td", /1/
    assert_select "tr.binding-row .badge-tester", "tester"

    get path_of(uploaded["report_url"])
    assert_select ".report-badges .badge-tester"
    get "/admin"
    assert_select "tr#admin-report-#{uploaded["id"]} .badge-tester", "tester @new-tester"
  end

  test "a handle that isn't a GitHub handle, or is already there, is refused" do
    sign_in_admin_with_github

    [ "not a handle", "-dash", "a" * 40, "maralcbr" ].each do |login|
      post "/admin/testers", params: { tester: { login: } }
      follow_redirect!
      assert_select ".flash-alert"
    end
    assert_equal [ "maralcbr" ], Tester.pluck(:login)
  end

  test "the admin removes a tester and can unbind a machine" do
    bind_machine "a", "maralcbr"
    uploaded = upload_report golden("m2-max-image2"), machine: "a"
    sign_in_admin_with_github

    delete "/admin/testers/maralcbr"
    assert_redirected_to "/admin/testers"
    assert_equal 0, Tester.count
    get path_of(uploaded["report_url"])
    assert_select ".report-badges .badge-community"

    delete "/admin/tester_bindings/#{TesterBinding.sole.id}"
    assert_redirected_to "/admin/testers"
    assert_equal 0, TesterBinding.count
    assert_equal "maralcbr", Report.sole.tester_login, "runs keep the handle they were uploaded under"
    upload_report golden("m2-max-image2"), machine: "a"
    assert_nil Report.newest_first.first.tester_login
  end
end
