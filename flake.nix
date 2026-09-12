{
  description = "usdAecoSync protocol, engine and host interface";
  inputs = {
    toolchain.url = "github:criad-com/usdaeco-toolchain?ref=v0.3.10";
    nixpkgs.follows = "toolchain/nixpkgs";
    core.url = "github:criad-com/usdaeco-core?ref=v0.9.5";
    core.inputs.toolchain.follows = "toolchain";
    core.inputs.nixpkgs.follows = "nixpkgs";
    axis.url = "github:criad-com/usdaeco-axis?ref=v0.1.5";
    axis.inputs.core.follows = "core";
    axis.inputs.toolchain.follows = "toolchain";
    axis.inputs.nixpkgs.follows = "nixpkgs";
  };
  outputs = { self, nixpkgs, toolchain, core, axis }:
    let
      eachSystem = nixpkgs.lib.genAttrs [ "aarch64-darwin" "x86_64-linux" ];
      forSystem = system:
        let
          kit = toolchain.lib.forSystem system;
          pkgs = nixpkgs.legacyPackages.${system};
          corePlugin = core.packages.${system}.default;
          axisPlugin = axis.packages.${system}.default;
          schema = kit.buildCodelessSchema { name = "usdAecoSync"; src = self; deps = [ corePlugin axisPlugin ]; };
          plugins = kit.pluginSet { plugins = [ schema ]; };
          setup = ''
            export TOOLCHAIN_DIR=${toolchain}
            export CORE_PLUGIN_DIR=${corePlugin}/plugins/usdAeco/resources
            export AXIS_PLUGIN_DIR=${axisPlugin}/plugins/usdAecoAxis/resources
            export AECO_CORE_ROOT=${core}
            export AECO_AXIS_ROOT=${axis}
            export PXR_PLUGINPATH_NAME=$CORE_PLUGIN_DIR:$AXIS_PLUGIN_DIR:${plugins}
          '';
          example = pkgs.writeShellApplication {
            name = "example";
            runtimeInputs = [ kit.pythonEnv kit.usd-dev ];
            text = setup + ''
              cp -R ${self} example-work
              chmod -R u+w example-work
              env -u PYTHONPATH PYTHONPATH=${core}:example-work python example-work/check.py "$@"
            '';
          };
          render = pkgs.writeShellApplication {
            name = "render";
            runtimeInputs = [ kit.pythonEnv kit.usd-dev ];
            text = setup + ''
              env -u PYTHONPATH usdaeco-render ${self}/usdAecoSync/examples/minimal.usda \
                --cameras ${self}/usdAecoSync/examples/cameras.usda "$@"
            '';
          };
        in { inherit kit pkgs schema plugins setup example render; };
    in {
      packages = eachSystem (system: let p = forSystem system; in {
        default = p.schema;
        pluginSet = p.plugins;
      });
      checks = eachSystem (system: let p = forSystem system; in {
        library = p.pkgs.runCommand "usdAecoSync-check" {
          nativeBuildInputs = [ p.kit.pythonEnv p.kit.usd-dev ];
        } (p.setup + ''
          cp -R ${self} source
          chmod -R u+w source
          cd source
          env -u PYTHONPATH PYTHONPATH=${core}:$PWD python check.py
          mkdir -p "$out"
        '');
        structure = p.pkgs.runCommand "usdAecoSync-structure" {
          nativeBuildInputs = [ p.kit.pythonEnv ];
        } (p.setup + ''
          env -u PYTHONPATH usdaeco-check structure ${self}
          mkdir -p "$out"
        '');
      });
      devShells = eachSystem (system: let p = forSystem system; in {
        default = p.pkgs.mkShell {
          packages = [ p.kit.pythonEnv p.kit.usd-dev ];
          shellHook = p.setup + "unset PYTHONPATH";
        };
      });
      apps = eachSystem (system: let p = forSystem system; in {
        example = { type = "app"; program = "${p.example}/bin/example"; };
        render = { type = "app"; program = "${p.render}/bin/render"; };
      });
    };
}
