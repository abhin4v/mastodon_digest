{ pkgs ? import <nixpkgs> {} }:
let
  my-python-packages = ps: with ps; [
    scipy
    mastodon-py
    jinja2
    ipython
    beautifulsoup4
  ];
  my-python = pkgs.python311.withPackages my-python-packages;
in my-python.env
