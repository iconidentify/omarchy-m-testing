# A machine key bound to the GitHub account that signed in on that machine
# (omarchy-m-test --sign-in, the GitHub device flow). machine_id is the
# report grouping key (MachineSignature#machine_id), never shown or exported.
# Signing in again on the same machine rebinds it.
class TesterBinding < ApplicationRecord
  normalizes :github_login, with: ->(login) { login.to_s.downcase }
  validates :machine_id, presence: true, uniqueness: true
  validates :github_login, format: { with: Tester::LOGIN }
  validates :github_id, presence: true

  def self.bind!(machine_id:, identity:)
    # The row locked (FOR UPDATE): a sign-out deleting it waits, then finds it's another sign-in and leaves it.
    transaction do
      binding = lock.find_or_initialize_by(machine_id:)
      # updated_at is this sign-in's (sign_in_id) even when nothing else changed.
      binding.update!(github_login: identity.login, github_id: identity.id, updated_at: Time.current)
      binding
    end
  end

  # Which sign-in this is (its time, in microseconds): a sign-out names it, so a copy of one made before
  # the machine signed in again unbinds nothing.
  def sign_in_id = (updated_at.to_r * 1_000_000).to_i.to_s

  def self.login_for(machine_id) = machine_id && find_by(machine_id:)&.github_login

  def tester? = Tester.allowlisted?(github_login)
  def reports = Report.where(machine_id:)
end
