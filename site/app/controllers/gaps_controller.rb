class GapsController < ApplicationController
  def show
    @gaps = KernelGaps.new(Report.visible.to_a)
  end
end
