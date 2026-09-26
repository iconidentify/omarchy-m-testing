# Serves the one-line installer (curl -fsSL https://omarchy-m-testing.org/install | bash)
# from ../installer/install.sh, or INSTALLER_PATH when the site is deployed
# without the rest of the repo. Not ApplicationController: curl isn't a browser.
class InstallerController < ActionController::Base
  def self.path
    Pathname(ENV.fetch("INSTALLER_PATH") { Rails.root.join("..", "installer", "install.sh").to_s })
  end

  def show
    expires_in 5.minutes, public: true
    send_data self.class.path.read, type: "text/x-shellscript; charset=utf-8", disposition: "inline", filename: "install.sh"
  end
end
