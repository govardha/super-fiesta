def userdata_customizer(params, userdata):
    for k, v in params.items():
        userdata = userdata.replace(k, v)

    return userdata
