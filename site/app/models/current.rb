# Per-request memo: the tester allowlist and the verified passes regressions
# are judged against are read once per request.
class Current < ActiveSupport::CurrentAttributes
  attribute :tester_logins, :regressions
end
