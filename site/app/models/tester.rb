# The tester allowlist: GitHub handles, kept lowercase (GitHub handles are
# case-insensitive). A run counts as a tester run when its machine was bound
# to an allowlisted handle when it was uploaded (TesterBinding, Report#tester?);
# removing a handle stops its runs counting, adding it back restores them.
class Tester < ApplicationRecord
  # GitHub's rule: letters, digits and single hyphens, not at either end, at most 39.
  LOGIN = /\A[a-z\d](?:[a-z\d]|-(?=[a-z\d])){0,38}\z/

  normalizes :login, with: ->(login) { login.to_s.strip.delete_prefix("@").downcase }
  validates :login, format: { with: LOGIN, message: "isn't a GitHub handle" }, uniqueness: true

  def self.logins = Current.tester_logins ||= pluck(:login).to_set
  def self.allowlisted?(login) = login.present? && logins.include?(login.downcase)

  def bindings = TesterBinding.where(github_login: login)

  # The GitHub account this handle is pinned to: the first to sign in with it.
  def account?(id) = github_id.nil? || github_id == id
  def pin!(id) = github_id.nil? && update!(github_id: id)

  def to_param = login
end
