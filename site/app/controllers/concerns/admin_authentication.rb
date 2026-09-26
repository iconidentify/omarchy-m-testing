# v0.1 admin: one secret token, ADMIN_TOKEN (GitHub sign-in replaces it in
# ticket 19). Signing in keeps a digest of the token in the encrypted session
# cookie for SESSION_HOURS, so changing ADMIN_TOKEN signs every admin out.
# Without ADMIN_TOKEN there is no admin at all.
module AdminAuthentication
  extend ActiveSupport::Concern

  SESSION_HOURS = 12

  included do
    helper_method :admin?
  end

  def self.token = ENV["ADMIN_TOKEN"].presence
  def self.digest(token) = OpenSSL::Digest::SHA256.hexdigest("omarchy-m-testing admin #{token}")

  def self.valid?(token)
    AdminAuthentication.token.present? && token.present? &&
      ActiveSupport::SecurityUtils.secure_compare(digest(token), digest(AdminAuthentication.token))
  end

  private

  def admin?
    AdminAuthentication.token.present? && session[:admin].present? && session[:admin_until].to_i > Time.current.to_i &&
      ActiveSupport::SecurityUtils.secure_compare(session[:admin].to_s, AdminAuthentication.digest(AdminAuthentication.token))
  end

  def sign_in_admin
    session[:admin] = AdminAuthentication.digest(AdminAuthentication.token)
    session[:admin_until] = SESSION_HOURS.hours.from_now.to_i
  end

  def require_admin
    raise ActionController::RoutingError, "Not Found" if AdminAuthentication.token.nil?

    render "admin/sessions/new", status: :unauthorized unless admin?
  end
end
