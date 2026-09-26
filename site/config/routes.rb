Rails.application.routes.draw do
  # www.omarchy-m-testing.org (www. + CANONICAL_HOST) redirects to the apex, path and query kept.
  canonical_host = ENV.fetch("CANONICAL_HOST", "omarchy-m-testing.org")
  constraints(->(request) { request.host == "www.#{canonical_host}" }) do
    match "(*path)", via: :all, format: false,
      to: redirect(status: 301) { |_params, request| "#{request.protocol}#{canonical_host}#{request.port_string}#{request.fullpath}" }
  end

  root "pages#home"
  get "install" => "installer#show", as: :install
  get "matrix" => "matrix#show", as: :matrix
  get "gaps" => "gaps#show", as: :gaps
  get "data" => "pages#data", as: :data
  resources :models, only: %i[index show], param: :board
  resources :features, only: %i[index show]

  namespace :api do
    namespace :v1 do
      resources :reports, only: %i[index create]
      get "checks" => "exports#checks", as: :checks
      get "matrix" => "exports#matrix", as: :matrix
    end
  end

  resources :reports, only: %i[index show destroy] do
    get :deletion, on: :member
  end

  namespace :admin do
    root "reports#index"
    resource :session, only: %i[create destroy]
    resources :reports, only: :destroy do
      member do
        patch :hide
        patch :unhide
      end
    end
  end

  get "up" => "rails/health#show", as: :rails_health_check
end
