# A Mac model (board) on an Omarchy stack and version: one row of the matrix.
Configuration = Data.define(:board, :stack, :version) do
  def stack_words = Report::STACK_WORDS.fetch(stack, stack)
  def label = "#{stack_words} #{version}"
end
