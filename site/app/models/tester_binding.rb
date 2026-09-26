# A machine key bound to the GitHub account that signed in on that machine
# (omarchy-m-test --sign-in, the GitHub device flow). machine_id is the
# report grouping key (MachineSignature#machine_id), never shown or exported.
# Signing in again on the same machine rebinds it.
class TesterBinding < ApplicationRecord
  normalizes :github_login, with: ->(login) { login.to_s.downcase }
  validates :machine_id, presence: true, uniqueness: true
  validates :github_login, :github_id, presence: true

  def self.bind!(machine_id:, identity:)
    binding = find_or_initialize_by(machine_id:)
    binding.update!(github_login: identity.login, github_id: identity.id)
    binding
  end

  def self.login_for(machine_id) = machine_id && find_by(machine_id:)&.github_login

  def tester? = Tester.allowlisted?(github_login)
  def reports = Report.where(machine_id:)
end
