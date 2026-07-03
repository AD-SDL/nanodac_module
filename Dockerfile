FROM ghcr.io/ad-sdl/madsci:latest

LABEL org.opencontainers.image.source=https://github.com/AD-SDL/nanodac_module
LABEL org.opencontainers.image.description="Driver and REST API for the Eurotherm nanodac temperature controller (Modbus/TCP)"
LABEL org.opencontainers.image.licenses=MIT

#########################################
# Module specific logic goes below here #
#########################################

ARG USER_ID=9999
ARG GROUP_ID=9999

COPY ./src /home/madsci/nanodac_module/src
COPY ./README.md /home/madsci/nanodac_module/README.md
COPY ./pyproject.toml /home/madsci/nanodac_module/pyproject.toml

RUN --mount=type=cache,target=/root/.cache \
    uv pip install --python ${MADSCI_VENV}/bin/python -e /home/madsci/nanodac_module && \
    chown -R ${USER_ID}:${GROUP_ID} /home/madsci/nanodac_module

CMD ["python", "-m", "nanodac_rest_node"]

#########################################
