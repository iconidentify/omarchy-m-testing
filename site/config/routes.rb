Rails.application.routes.draw do
  # www.omarchy-m-testing.org (www. + CANONICAL_HOST) redirects to the apex, path and query kept.
  canonical_host = ENV.fetch("CANONICAL_HOST", "omarchy-m-testing.org")
  constraints(->(request) { request.host == "www.#{canonical_host}" }) do
    match "(*path)", via: :all, format: false,
      to: redirect(status: 301) { |_params, request| "#{request.protocol}#{canonical_host}#{request.port_string}#{request.fullpath}" }
  end

  root "pages#home"
  get "install" => "installer#show", as: :install

  namespace :api do
    namespace :v1 do
      resources :reports, only: :create
    end
  end

  resources :reports, only: %i[show destroy] do
    get :deletion, on: :member
  end

  get "up" => "rails/health#show", as: :rails_health_check
end
