require "test_helper"

# Seam B: the home page, the one-line installer and the www redirect.
class SiteTest < ActionDispatch::IntegrationTest
  test "the installer is served as a shell script, byte for byte" do
    get "/install"

    assert_response :success
    assert_equal "text/x-shellscript", response.media_type
    assert_equal Rails.root.join("..", "installer", "install.sh").read, response.body
    assert_match %r{\A#!/usr/bin/env bash}, response.body
  end

  test "the installer pins the same release key as the release workflow and README" do
    key = Rails.root.join("..", "release", "allowed_signers").read.strip
    assert_includes InstallerController.path.read, "local allowed_signer='#{key}'"
    assert_includes Rails.root.join("..", "README.md").read, key.split.last(2).join(" ")
  end

  test "the home page shows the install command" do
    get "/"

    assert_response :success
    assert_select "#install", "curl -fsSL http://www.example.com/install | bash"
  end

  test "www redirects to the apex keeping path and query" do
    host! "www.omarchy-m-testing.org"
    get "/reports/abc/deletion?token=t"

    assert_response :moved_permanently
    assert_redirected_to "http://omarchy-m-testing.org/reports/abc/deletion?token=t"
  end

  test "the apex itself is not redirected" do
    host! "omarchy-m-testing.org"
    get "/install"

    assert_response :success
  end
end
