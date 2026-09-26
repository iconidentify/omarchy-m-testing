# New tables and one nullable column only, so the migration is instant and
# safe on the live database: existing reports stay community reports
# (tester_login NULL). The allowlist starts with the owner.
class CreateTestersAndTesterBindings < ActiveRecord::Migration[8.1]
  OWNER = "maralcbr"

  def up
    create_table :testers do |t|
      t.string :login, null: false
      # Pinned by the first sign-in with the handle (renamed handles are reissued).
      t.bigint :github_id
      t.timestamps
    end
    add_index :testers, :login, unique: true

    create_table :tester_bindings do |t|
      t.string :machine_id, null: false
      t.string :github_login, null: false
      t.bigint :github_id, null: false
      t.timestamps
    end
    add_index :tester_bindings, :machine_id, unique: true
    add_index :tester_bindings, :github_login

    add_column :reports, :tester_login, :string

    now = connection.quote(Time.current.utc)
    execute "INSERT INTO testers (login, created_at, updated_at) VALUES (#{connection.quote(OWNER)}, #{now}, #{now})"
  end

  def down
    remove_column :reports, :tester_login
    drop_table :tester_bindings
    drop_table :testers
  end
end
