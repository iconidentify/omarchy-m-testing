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
  get "aurora" => "aurora#show", as: :aurora
  get "benchmarks" => "benchmarks#show", as: :benchmarks
  get "data" => "pages#data", as: :data
  resources :models, only: %i[index show], param: :board
  resources :features, only: %i[index show]
  resources :candidates, only: %i[index show], format: false, constraints: { id: /#{CandidateSet::NAME.source}/ }
  get "auth/github/callback" => "admin/sessions#callback", as: :auth_github_callback

  namespace :api do
    namespace :v1 do
      resources :reports, only: %i[index create]
      resources :tester_bindings, only: :create
      resources :tester_requests, only: :create
      get "checks" => "exports#checks", as: :checks
      get "matrix" => "exports#matrix", as: :matrix
      get "benchmarks" => "exports#benchmarks", as: :benchmarks
      get "aurora" => "exports#aurora", as: :aurora
    end
  end

  resources :reports, only: %i[index show destroy] do
    get :deletion, on: :member
  end

  namespace :admin do
    root "reports#index"
    resource :session, only: %i[create destroy]
    resources :testers, only: %i[index create destroy], constraints: { id: /[A-Za-z0-9-]+/ }
    resources :tester_bindings, only: :destroy
    resources :reports, only: :destroy do
      member do
        patch :hide
        patch :unhide
      end
    end
  end

  get "up" => "rails/health#show", as: :rails_health_check
end
