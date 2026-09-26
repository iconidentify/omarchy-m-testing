require "test_helper"

# Seam B: every report must carry a valid signature by its machine's key.
# Reports group by machine through a keyed digest of that key; neither the key
# nor the signature is kept, shown or exported.
class MachineSignatureTest < ActionDispatch::IntegrationTest
  test "the reports the CLI signed are accepted as they are, whatever characters they hold" do
    assert_equal 2, GoldenReports.signed_paths.size
    GoldenReports.signed_paths.each do |path|
      upload_report File.read(path)
      assert_response :created, "#{File.basename(path)}: #{response.body}"
    end
    assert_equal 1, Report.distinct.count(:machine_id)
    assert_includes Report.all.map(&:kernel), "7.1.12-\"asahi\"\\ärm/💻-ARCH"
  end

  test "a report changed after it was signed is refused and not stored" do
    tampered = [
      JSON.parse(File.read(GoldenReports.signed_paths.first)).tap { |r| r["checks"][0]["status"] = "fail" },
      JSON.parse(File.read(GoldenReports.signed_paths.first)).tap { |r| r["machine"]["kernel"] = "7.1.13-1-ARCH" },
      TestMachines.sign(golden("m2-max-image2")).tap { |r| r["catalogue_version"] += 1 }
    ]

    tampered.each do |report|
      body = upload_report report.to_json
      assert_response :unprocessable_content
      assert_equal "The report's signature is not valid, so it was refused.", body["error"]
      assert_equal [ "signature: it doesn't match the report: the report was changed after it was signed" ], body["details"]
    end
    assert_equal 0, Report.count
  end

  test "a signature by another key than the report's public key is refused" do
    report = TestMachines.sign(golden("m2-max-image2"), "mallory")
    report["signature"]["public_key"] = TestMachines.public_key("a")

    body = upload_report report.to_json

    assert_response :unprocessable_content
    assert_equal [ "signature: it was made with a different key than the report's public_key" ], body["details"]
  end

  test "signatures that aren't SSH report signatures are refused" do
    signature = TestMachines.sign(golden("m2-max-image2"))["signature"]["signature"]
    blob = Base64.decode64(signature.lines[1..-2].join)
    other_namespace = blob.sub("omarchy-m-test-report", "omarchy-m-test-xxxxxx")
    rearmor = ->(bytes) { "-----BEGIN SSH SIGNATURE-----\n#{Base64.strict_encode64(bytes).scan(/.{1,70}/).join("\n")}\n-----END SSH SIGNATURE-----" }
    {
      rearmor.call(other_namespace) => "signature: it isn't a report signature (namespace)",
      rearmor.call(blob[0, 40]) => "signature: it is cut short",
      rearmor.call(blob + "x") => "signature: it has trailing bytes",
      "-----BEGIN SSH SIGNATURE-----\nnot base64!\n-----END SSH SIGNATURE-----" => nil
    }.each do |armored, detail|
      report = TestMachines.sign(golden("m2-max-image2"))
      report["signature"]["signature"] = armored

      body = upload_report report.to_json

      assert_response :unprocessable_content
      assert_equal [ detail ], body["details"] if detail
    end
    assert_equal 0, Report.count
  end

  test "an unsigned report is refused with upgrade instructions" do
    body = upload_report golden("m2-max-image2").to_json

    assert_response :unprocessable_content
    assert_equal "This report isn't signed with its Mac's key, which the site requires. omarchy-m-test signs every report by itself " \
                 "(it needs ssh-keygen, from openssh). Update omarchy-m-test (curl -fsSL http://www.example.com/install | bash) and run it again.",
                 body["error"]
    assert_equal [ "signature is missing" ], body["details"]
    assert_equal 0, Report.count
  end

  test "the machine is a keyed digest of its key; the key and signature aren't kept, shown or exported" do
    upload_report golden("m2-max-image2"), machine: "a"
    report = Report.sole

    assert_equal TestMachines.machine_id("a"), report.machine_id
    assert_match(/\Akey:\h{20}\z/, report.machine_id)
    assert_equal golden("m2-max-image2"), report.body
    key = TestMachines.public_key("a").split.last
    [ "/reports/#{report.public_id}", "/api/v1/reports.json", "/api/v1/reports.csv", "/api/v1/checks.csv", "/matrix" ].each do |path|
      get path
      assert_not_includes response.body, key, path
      assert_not_includes response.body, report.machine_id, path
    end
    assert_not_includes Report.connection.select_value("SELECT body::text FROM reports"), key
  end

  test "reports signed by the same key are one machine, from any network; different keys are different machines" do
    upload_report golden("m2-max-image2"), machine: "a", ip: "10.0.0.1"
    upload_report golden("m2-max-image2"), machine: "a", ip: "192.0.2.7"
    upload_report golden("m2-max-image2"), machine: "b", ip: "10.0.0.1"

    assert_equal [ 1, 2 ], Report.group(:machine_id).count.values.sort
    get "/matrix"
    assert_select %(tr.matrix-row[data-board="j416c"] td[data-feature="gpu"][data-state="works"])
  end

  test "the signature, which holds the public key, never reaches the log" do
    report = TestMachines.sign(golden("m2-max-image2"))
    filtered = ActiveSupport::ParameterFilter.new(Rails.application.config.filter_parameters).filter(report)

    assert_equal "[FILTERED]", filtered["signature"]
    assert_equal report["machine"], filtered["machine"]
  end

  test "reports the site refuses anyway don't count towards the machine's limit" do
    limit = Api::V1::ReportsController::UPLOADS_PER_HOUR_PER_MACHINE
    (limit + 1).times { |n| upload_report golden("m2-max-image2").tap { |r| r["checks"][0]["id"] = "made.up" }, ip: "10.0.1.#{n}" }
    assert_response :unprocessable_content

    upload_report golden("m2-max-image2"), ip: "10.0.2.1"
    assert_response :created
  end
end
