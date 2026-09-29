# Per-request memo: the tester allowlist and the verified passes regressions
# are judged against, and the candidate sets runs name, are read once per request.
class Current < ActiveSupport::CurrentAttributes
  attribute :tester_logins, :regressions, :candidate_set_names
end
