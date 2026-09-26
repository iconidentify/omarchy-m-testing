# Nullable columns only, so the migration is instant and safe on the live
# table: existing reports stay visible (hidden_at NULL) and share one unknown
# machine (machine_id NULL) until they're re-uploaded.
class AddHiddenAtAndMachineIdToReports < ActiveRecord::Migration[8.1]
  def change
    add_column :reports, :hidden_at, :datetime
    add_column :reports, :machine_id, :string
  end
end
