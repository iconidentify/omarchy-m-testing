class PagesController < ApplicationController
  def home
    @matrix = CompatibilityMatrix.visible
  end

  def data
  end
end
