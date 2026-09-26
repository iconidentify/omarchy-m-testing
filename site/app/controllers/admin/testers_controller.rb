module Admin
  # The tester allowlist, and which machines each handle signed in on.
  class TestersController < ApplicationController
    before_action :require_admin

    def index
      @testers = Tester.order(:login)
      @tester = Tester.new
      @bindings = TesterBinding.order(:github_login, :created_at)
      @report_counts = Report.where(machine_id: @bindings.map(&:machine_id)).group(:machine_id).count
    end

    def create
      @tester = Tester.new(login: params.dig(:tester, :login))
      if @tester.save
        redirect_to admin_testers_path, notice: "Added @#{@tester.login} to the testers."
      else
        redirect_to admin_testers_path, alert: "@#{@tester.login} #{@tester.errors[:login].to_sentence}."
      end
    end

    def destroy
      tester = Tester.find_by!(login: params[:id].to_s.downcase)
      tester.destroy!
      redirect_to admin_testers_path, notice: "Removed @#{tester.login} from the testers: their runs no longer count as tester runs."
    end
  end
end
