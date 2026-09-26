# Per-request memo: the tester allowlist is read once per request.
class Current < ActiveSupport::CurrentAttributes
  attribute :tester_logins
end
