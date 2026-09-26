class FeaturesController < ApplicationController
  def index
    @matrix = CompatibilityMatrix.visible
    @features = Catalogue.features.group_by { |feature| feature.fetch("layer") }
  end

  def show
    @feature = Catalogue.feature(params[:id]) or raise ActiveRecord::RecordNotFound
    @matrix = CompatibilityMatrix.visible
    @rows = @matrix.rows_for_feature(@feature.fetch("id"))
  end
end
