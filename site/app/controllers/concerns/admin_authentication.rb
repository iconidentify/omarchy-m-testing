# Admin sign-in with GitHub (the OAuth app's web flow, Github): the admin is
# any handle in ADMIN_GITHUB_LOGINS (comma-separated). Signing in keeps the
# handle in the encrypted session cookie for SESSION_HOURS; taking a handle
# out of ADMIN_GITHUB_LOGINS signs it out.
#
# Until GitHub sign-in is set up (GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET and
# ADMIN_GITHUB_LOGINS), the v0.1 secret ADMIN_TOKEN still signs in, so a
# deploy never locks the admin out; once it is set up the token is ignored.
# With neither there is no admin at all.
module AdminAuthentication
  extend ActiveSupport::Concern

  SESSION_HOURS = 12

  included do
    helper_method :admin?, :admin_login
  end

  def self.logins = ENV.fetch("ADMIN_GITHUB_LOGINS", "").split(/[\s,]+/).map { |login| login.delete_prefix("@").downcase }.compact_blank
  def self.github? = Github.configured? && logins.any?
  def self.admin_login?(login) = login.present? && logins.include?(login.to_s.downcase)
  def self.token = github? ? nil : ENV["ADMIN_TOKEN"].presence
  def self.available? = github? || token.present?
  def self.digest(token) = OpenSSL::Digest::SHA256.hexdigest("omarchy-m-testing admin #{token}")

  def self.valid?(token)
    AdminAuthentication.token.present? && token.present? &&
      ActiveSupport::SecurityUtils.secure_compare(digest(token), digest(AdminAuthentication.token))
  end

  private

  def admin?
    return false unless session[:admin_until].to_i > Time.current.to_i

    if AdminAuthentication.github?
      AdminAuthentication.admin_login?(session[:admin_login])
    else
      AdminAuthentication.token.present? && session[:admin].present? &&
        ActiveSupport::SecurityUtils.secure_compare(session[:admin].to_s, AdminAuthentication.digest(AdminAuthentication.token))
    end
  end

  def admin_login = (session[:admin_login] if admin?)

  def sign_in_admin(login: nil)
    reset_session
    if login
      session[:admin_login] = login.downcase
    else
      session[:admin] = AdminAuthentication.digest(AdminAuthentication.token)
    end
    session[:admin_until] = SESSION_HOURS.hours.from_now.to_i
  end

  def require_admin
    raise ActionController::RoutingError, "Not Found" unless AdminAuthentication.available?

    render "admin/sessions/new", status: :unauthorized unless admin?
  end
end
