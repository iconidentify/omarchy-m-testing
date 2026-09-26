class CreateReports < ActiveRecord::Migration[8.1]
  def change
    create_table :reports do |t|
      t.string :public_id, null: false
      t.string :deletion_token_digest, null: false
      t.integer :schema_version, null: false
      t.jsonb :body, null: false
      t.timestamps
    end
    add_index :reports, :public_id, unique: true
  end
end
