require "test_helper"

# Seam B: omarchy-m-test --status and --sign-out. The CLI sends the golden
# requests (signed by its fixture machine key, dated at its recorded clock);
# the site says whom the machine is bound to, or unbinds it.
class TesterRequestsTest < ActionDispatch::IntegrationTest
  FIXTURE_MACHINE_REPORT = -> { File.read(GoldenReports.signed_paths.find { |path| path.end_with?("/m2-max-image2.json") }) }

  setup do
    configure_github
    Tester.create!(login: "maralcbr")
    github.issue(GoldenSignIn::TOKEN, "MaralcBR", id: 4242)
  end

  def request_at(name, at = GoldenTesterRequests::AT, body = GoldenTesterRequests.text(name))
    travel_to(at) { tester_request(body) }
  end

  # The golden sign-in, made a little before the golden requests are dated.
  def sign_in_before = travel_to(GoldenTesterRequests::AT - 5.minutes) { sign_in_tester }

  def signed(request, name: "a", at: GoldenTesterRequests::AT.to_i, **fields)
    TestMachines.sign({ "request_version" => 1, "request" => request, "requested_at" => at, **fields.transform_keys(&:to_s) }, name,
                      namespace: MachineSignature::TESTER_NAMESPACE)
  end

  GOLDEN_SIGN_IN_ID = ((GoldenTesterRequests::AT.to_i - 300) * 1_000_000).to_s

  test "status: a machine that never signed in isn't signed in" do
    assert_equal({ "signed_in" => false }, request_at("status"))
    assert_response :ok
  end

  test "status: after the golden sign-in, the machine is signed in as its handle, a tester while it's on the allowlist" do
    sign_in_before
    assert_equal({ "signed_in" => true, "login" => "maralcbr", "tester" => true, "sign_in" => GOLDEN_SIGN_IN_ID }, request_at("status"))
    assert_equal GoldenTesterRequests.json("sign-out")["sign_in"], GOLDEN_SIGN_IN_ID, "the golden sign-out names this sign-in"

    Tester.delete_all
    assert_equal({ "signed_in" => true, "login" => "maralcbr", "tester" => false, "sign_in" => GOLDEN_SIGN_IN_ID }, request_at("status"))
  end

  test "sign-out unbinds the machine: its later runs are community runs, earlier ones keep their handle" do
    sign_in_before
    upload_report FIXTURE_MACHINE_REPORT.call
    assert_equal "maralcbr", Report.sole.tester_login

    assert_equal({ "signed_in" => false, "signed_out" => "maralcbr" }, request_at("sign-out"))
    assert_equal 0, TesterBinding.count
    assert_equal({ "signed_in" => false }, request_at("status"))

    uploaded = upload_report FIXTURE_MACHINE_REPORT.call
    assert_equal false, uploaded["tester"]
    assert_equal [ "maralcbr", nil ], Report.order(:id).pluck(:tester_login)
  end

  test "sign-out of a machine that isn't bound says so and changes nothing else" do
    bind_machine("b", "someone")
    assert_equal({ "signed_in" => false, "signed_out" => nil }, request_at("sign-out"))
    assert_equal 1, TesterBinding.count
  end

  test "a machine only ever signs itself out" do
    travel_to(GoldenTesterRequests::AT - 5.minutes) do
      bind_machine("a", "maralcbr")
      bind_machine("b", "someone")
    end
    travel_to(GoldenTesterRequests::AT) { tester_request signed("sign-out", name: "b", sign_in: GOLDEN_SIGN_IN_ID) }
    assert_equal({ "signed_in" => false, "signed_out" => "someone" }, response.parsed_body)
    assert_equal [ TestMachines.machine_id("a") ], TesterBinding.pluck(:machine_id)
  end

  test "a request dated more than a day from the site's clock is refused" do
    sign_in_before
    body = request_at("sign-out", GoldenTesterRequests::AT + 25.hours)
    assert_response :unprocessable_content
    assert_match "dated more than a day from the site's clock", body["error"]
    assert_equal 1, TesterBinding.count

    request_at("sign-out", GoldenTesterRequests::AT - 25.hours)
    assert_response :unprocessable_content
    request_at("sign-out", GoldenTesterRequests::AT + 23.hours)
    assert_response :ok
    assert_equal 0, TesterBinding.count
  end

  test "a copy of a sign-out, replayed after the machine signed in again, unbinds nothing" do
    sign_in_before
    request_at("sign-out")
    assert_equal 0, TesterBinding.count

    travel_to(GoldenTesterRequests::AT - 1.minute) { sign_in_tester } # dated before the copied sign-out: still a later sign-in
    body = request_at("sign-out", GoldenTesterRequests::AT + 3.minutes)
    assert_response :conflict
    assert_match "signed in again after this sign-out was made", body["error"]
    assert_equal "maralcbr", TesterBinding.sole.github_login
  end

  test "a request changed after it was signed, or signed as a report, is refused" do
    sign_in_before
    changed = GoldenTesterRequests.json("sign-out").merge("sign_in" => "1")
    request_at("sign-out", GoldenTesterRequests::AT, changed.to_json)
    assert_response :unprocessable_content
    assert_match "changed after it was signed", response.parsed_body["error"]

    as_report = TestMachines.sign({ "request_version" => 1, "request" => "sign-out", "requested_at" => GoldenTesterRequests::AT.to_i,
                                    "sign_in" => GOLDEN_SIGN_IN_ID })
    request_at("sign-out", GoldenTesterRequests::AT, as_report.to_json)
    assert_response :unprocessable_content
    assert_match "namespace", response.parsed_body["error"]
    assert_equal 1, TesterBinding.count
  end

  test "a sign-in can't pass for a request, nor anything else" do
    [ GoldenSignIn.json, GoldenTesterRequests.json("status").except("signature"), GoldenTesterRequests.json("status").merge("extra" => 1),
      GoldenTesterRequests.json("status").merge("request" => "delete-everything"), GoldenTesterRequests.json("status").merge("requested_at" => "now"),
      GoldenTesterRequests.json("status").merge("request_version" => 2), GoldenTesterRequests.json("status").merge("sign_in" => "1"),
      GoldenTesterRequests.json("sign-out").except("sign_in"), GoldenTesterRequests.json("sign-out").merge("sign_in" => "x"), [ 1 ] ].each do |body|
      request_at("status", GoldenTesterRequests::AT, body.to_json)
      assert_response :unprocessable_content, body.inspect
    end
    request_at("status", GoldenTesterRequests::AT, "{")
    assert_response :bad_request
  end
end
