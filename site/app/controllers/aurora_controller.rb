class AuroraController < ApplicationController
  def show
    @support = AuroraSupport.visible
  end
end
