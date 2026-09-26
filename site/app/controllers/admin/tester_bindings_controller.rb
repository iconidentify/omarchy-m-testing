module Admin
  # Unbinds a machine from its GitHub handle: its later runs are community
  # runs until someone signs in on it again. Runs already uploaded keep the
  # handle they were uploaded under.
  class TesterBindingsController < ApplicationController
    before_action :require_admin

    def destroy
      binding = TesterBinding.find(params[:id])
      binding.destroy!
      redirect_to admin_testers_path, notice: "Unbound a machine from @#{binding.github_login}."
    end
  end
end
