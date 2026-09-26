module Admin
  class ReportsController < ApplicationController
    before_action :require_admin
    before_action :set_report, except: :index

    def index
      @reports = Report.newest_first
    end

    def hide
      @report.update!(hidden_at: Time.current)
      redirect_to admin_root_path, notice: "Hidden #{@report.public_id}."
    end

    def unhide
      @report.update!(hidden_at: nil)
      redirect_to admin_root_path, notice: "Shown #{@report.public_id} again."
    end

    def destroy
      @report.destroy!
      redirect_to admin_root_path, notice: "Deleted #{@report.public_id}."
    end

    private

    def set_report
      @report = Report.find_by!(public_id: params[:id])
    end
  end
end
