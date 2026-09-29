# A Mac model (board) on an Omarchy stack, release and build: one row of the
# matrix. build is the Build's words, or nil for a reference run or when the
# builds of a release are merged.
Configuration = Data.define(:board, :stack, :version, :build) do
  def initialize(board:, stack:, version:, build: nil) = super

  def stack_words = Report::STACK_WORDS.fetch(stack, stack)
  def release_label = "#{stack_words} #{version}"
  def label = build ? "#{release_label} · build #{build}" : release_label
  def build_id = build&.split(" ", 2)&.first
end
