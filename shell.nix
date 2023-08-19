{ pkgs ? import <nixpkgs> {} }:
let
  my-python-packages = ps: with ps; [
    scipy
    mastodon-py
    jinja2
    ipython
  ];
  my-python = pkgs.python39.withPackages my-python-packages;
in my-python.env
