{ pkgs ? import <nixpkgs> {} }:
let
  my-python-packages = ps: with ps; [
    scipy
    mastodon-py
    requests
    types-requests
    jinja2
    beautifulsoup4
    types-beautifulsoup4
    ipython
    mypy
  ];
  my-python = pkgs.python311.withPackages my-python-packages;
in my-python.env
