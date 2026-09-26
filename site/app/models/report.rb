# One uploaded report. The body is the schema-validated report exactly as the
# CLI sent it; public_id is the unguessable id in its URL. Only a digest of the
# deletion token is stored; the token itself is returned once, at upload.
class Report < ApplicationRecord
  has_secure_token :public_id, length: 24

  attr_reader :deletion_token

  validates :body, :schema_version, presence: true

  before_validation :issue_deletion_token, on: :create

  def self.digest(token)
    OpenSSL::Digest::SHA256.hexdigest(token.to_s)
  end

  def deletion_token_matches?(token)
    token.present? && ActiveSupport::SecurityUtils.secure_compare(deletion_token_digest, self.class.digest(token))
  end

  def machine = body.fetch("machine")
  def checks = body.fetch("checks")

  def to_param = public_id

  private

  def issue_deletion_token
    @deletion_token = SecureRandom.urlsafe_base64(32)
    self.deletion_token_digest = self.class.digest(@deletion_token)
  end
end
