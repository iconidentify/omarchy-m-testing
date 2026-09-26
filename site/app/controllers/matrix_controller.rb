class MatrixController < ApplicationController
  def show
    @stack = params[:stack].presence_in(CompatibilityMatrix::STACKS)
    @matrix = CompatibilityMatrix.visible(stack: @stack)
  end
end
